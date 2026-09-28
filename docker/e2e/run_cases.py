"""Тест-кейсы guardrail через LiteLLM: что ушло в модель и что получил пользователь.

    python run_cases.py run --label before --litellm http://127.0.0.1:24000 --pii http://127.0.0.1:25001 \\
        --log log/before/upstream.jsonl --project pii-before --out results/before.json
    python run_cases.py run --label after  --litellm http://127.0.0.1:34000 --pii http://127.0.0.1:35001 \\
        --log log/after/upstream.jsonl  --project pii-after  --out results/after.json
    python run_cases.py report results/before.json results/after.json > results/report.md

--real-models: кейсы с настоящими моделями (падежи, порча меток, время рассуждений).
--project: имя compose-проекта — для кейсов с остановкой pii-service и проверки логов.
Все данные в кейсах синтетические (ИНН и СНИЛС — с верными контрольными суммами).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

KEY = "sk-e2e-master-key"
INN = "386018159000"
SNILS = "830-166-131 65"

PERSONAL = (f"Сотрудник Петров Иван Сергеевич, ИНН {INN}, СНИЛС {SNILS}, паспорт 2515 123456, "
            "тел. +7 914 123-45-67, e-mail i.petrov@example.ru, проживает: 666904, Иркутская обл., "
            "г. Бодайбо, ул. Урицкого, д. 33, кв. 5.")
ORIGINALS = ["Петров", "Иван", INN, SNILS, "2515 123456", "914 123-45-67", "i.petrov@example.ru", "Урицкого"]
LETTER = ("Напиши короткое вежливое письмо от имени начальника отдела кадров Сидоровой Анны Викторовны "
          f"сотруднику Петрову Ивану Сергеевичу с просьбой предоставить копию СНИЛС {SNILS} до пятницы. "
          "Обратись к нему по имени-отчеству.")


class Stand:
    def __init__(self, args):
        self.litellm, self.pii, self.log, self.project = args.litellm, args.pii, args.log, args.project

    def chat(self, model, messages, stream=False, timeout=300, **kw):
        body = {"model": model, "messages": messages, "stream": stream, **kw}
        req = urllib.request.Request(f"{self.litellm}/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return {"status": e.code, "error": e.read().decode()[:300], "t": time.time() - t0}
        except Exception as e:
            return {"status": 0, "error": type(e).__name__, "t": time.time() - t0}
        if not stream:
            d = json.load(resp)
            msg = d["choices"][0]["message"]
            return {"status": 200, "text": msg.get("content"), "reasoning": msg.get("reasoning_content"),
                    "tool_args": [c["function"]["arguments"] for c in msg.get("tool_calls") or []],
                    "t": time.time() - t0}
        first, chunks, text, reasoning, tool_args = None, 0, [], [], {}
        for line in resp:
            line = line.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            d = json.loads(line[6:])
            for c in d.get("choices", []):
                delta = c.get("delta") or {}
                got = False
                if delta.get("content"):
                    text.append(delta["content"]); got = True
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"]); got = True
                for tc in delta.get("tool_calls") or []:
                    a = (tc.get("function") or {}).get("arguments")
                    if a:
                        tool_args[tc.get("index", 0)] = tool_args.get(tc.get("index", 0), "") + a; got = True
                if got:
                    chunks += 1
                    first = first if first is not None else time.time() - t0
        return {"status": 200, "text": "".join(text), "reasoning": "".join(reasoning),
                "tool_args": [tool_args[k] for k in sorted(tool_args)], "chunks": chunks,
                "ttfb": first, "t": time.time() - t0}

    def upstream_count(self):
        return sum(1 for _ in open(self.log)) if os.path.exists(self.log) else 0

    def upstream_last(self):
        lines = open(self.log).read().splitlines()
        return json.loads(lines[-1])["body"]

    def analyze(self, text, language="en"):
        req = urllib.request.Request(f"{self.pii}/analyze", json.dumps({"text": text, "language": language}).encode(),
                                     {"Content-Type": "application/json"})
        try:
            return 200, json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            return e.code, None

    def compose(self, *args):
        return subprocess.run(["docker", "compose", "-p", self.project, *args],
                              capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))


def user(text):
    return [{"role": "user", "content": text}]


def sent_texts(body):
    parts = []
    for m in body.get("messages", []):
        c = m.get("content")
        parts.append(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
        for tc in m.get("tool_calls") or []:
            parts.append(tc["function"]["arguments"])
    return parts


def leaked(body, originals):
    joined = "\n".join(sent_texts(body))
    return [o for o in originals if o in joined]


def expected_echo(messages):
    return " | ".join(m["content"] for m in messages if m["role"] != "system")


# ── кейсы ────────────────────────────────────────────────────────────────────

CASES = []


def case(cid, title, check):
    def wrap(fn):
        CASES.append((cid, title, check, fn))
        return fn
    return wrap


@case("TC-01", "ПДн всех типов в одном сообщении", "в модель не ушло ни одного исходного значения; пользователю вернулся исходный текст")
def tc01(s):
    msgs = user(PERSONAL)
    r = s.chat("echo", msgs)
    body = s.upstream_last()
    leak = leaked(body, ORIGINALS)
    ok_resp = r.get("text") == expected_echo(msgs)
    sent = sent_texts(body)[-1]
    return (not leak and ok_resp), f"в модель: «{sent}»" + (f"; утекло: {leak}" if leak else "") + ("" if ok_resp else "; ответ не восстановлен")


@case("TC-02", "Номер карты и CVC (политика BLOCK)", "HTTP 400, до модели запрос не дошёл")
def tc02(s):
    n = s.upstream_count()
    r = s.chat("echo", user("Оплатите с карты 4111 1111 1111 1111, CVC 123."))
    return r["status"] == 400 and s.upstream_count() == n, f"HTTP {r['status']}, дошло до модели: {s.upstream_count() - n}"


@case("TC-03", "Ключ API в сообщении (TOKEN, BLOCK)", "HTTP 400, до модели запрос не дошёл")
def tc03(s):
    n = s.upstream_count()
    r = s.chat("echo", user("Вот мой ключ для отладки: sk-proj-7Hq2mZx9Lk3PvB8nR4tY6wQ1eS5dF0gJ2hK4lM6nP8qR0sT"))
    return r["status"] == 400 and s.upstream_count() == n, f"HTTP {r['status']}, дошло до модели: {s.upstream_count() - n}"


@case("TC-04", "sha256-digest образа и хэш коммита", "не считаются секретом, запрос проходит")
def tc04(s):
    r = s.chat("echo", user("Почему не стартует ghcr.io/berriai/litellm@sha256:a3715fa7ad8387941ab697259bd2881d68931657247a41984f90fae6d11c62bf "
                            "после коммита 3ceab7d4e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6?"))
    return r["status"] == 200, f"HTTP {r['status']}" + (f": {r.get('error', '')[:120]}" if r["status"] != 200 else "")


@case("TC-05", "Разные люди в разных сообщениях диалога", "у каждого человека своя замена; в ответе роли не перепутаны")
def tc05(s):
    msgs = [{"role": "user", "content": "Руководитель проекта — Сидорова Анна Викторовна."},
            {"role": "assistant", "content": "Понял."},
            {"role": "user", "content": "Исполнитель — Петров Иван Сергеевич. Кто руководитель и кто исполнитель?"}]
    r = s.chat("echo", msgs)
    sent = sent_texts(s.upstream_last())
    a = sent[-3].split("— ")[1].rstrip(".")
    b = sent[-1].split("— ")[1].split(".")[0]
    ok = a != b and r.get("text") == expected_echo(msgs)
    return ok, f"в модель: руководитель «{a}», исполнитель «{b}»; пользователю: «{r.get('text')}»"


@case("TC-06", "Один человек в разных сообщениях и падежах", "везде одна и та же замена")
def tc06(s):
    msgs = [{"role": "user", "content": "Сформируй приказ о премировании Петрова Ивана Сергеевича."},
            {"role": "assistant", "content": "Готово: приказ о премировании Петрова Ивана Сергеевича."},
            {"role": "user", "content": "Добавь, что Петров Иван Сергеевич ознакомлен."}]
    s.chat("echo", msgs)
    sent = sent_texts(s.upstream_last())
    first = re.search(r"премировании (.+?)\.", sent[-3]).group(1)
    last = re.search(r"что (.+?) ознакомлен", sent[-1]).group(1)
    # метка должна совпасть целиком, псевдоним — по основе фамилии (падеж может отличаться)
    same = first == last if first.startswith("<") else first.split()[0][:5] == last.split()[0][:5]
    return same, f"в модель: «{first}» … «{last}»"


@case("TC-07", "Повторное упоминание, которое NER пропускает", "фамилия не уходит в модель и во втором упоминании")
def tc07(s):
    msgs = user("Руководитель проекта — Сидорова Анна Викторовна. Позвоните Петрову по тел. +7 914 123-45-67 "
                "или Сидоровой на a.sidorova@example.ru. Исполнитель — Петров Иван Сергеевич.")
    r = s.chat("echo", msgs)
    body = s.upstream_last()
    leak = leaked(body, ["Сидоров", "Петров"])
    return not leak and r.get("text") == expected_echo(msgs), f"в модель: «{sent_texts(body)[-1]}»" + (f"; утекло: {leak}" if leak else "")


@case("TC-08", "Стрим ответа с ПДн", "ответ идёт частями с первых секунд; текст восстановлен, в т.ч. метки на стыке чанков")
def tc08(s):
    msgs = user(PERSONAL)
    r = s.chat("echo", msgs, stream=True)
    ok = r.get("text") == expected_echo(msgs) and r.get("chunks", 0) > 5
    return ok, f"чанков с текстом: {r.get('chunks')}, первый через {r.get('ttfb', 0):.2f} с, весь ответ {r['t']:.1f} с, восстановлен: {r.get('text') == expected_echo(msgs)}"


@case("TC-09", "reasoning_content (рассуждения модели)", "исходные значения восстановлены и в рассуждениях — обычный ответ и стрим")
def tc09(s):
    msgs = user(LETTER)
    exp = expected_echo(msgs)
    r1 = s.chat("echo-reasoning", msgs)
    r2 = s.chat("echo-reasoning", msgs, stream=True)
    ok = r1.get("reasoning") == exp and r2.get("reasoning") == exp
    return ok, f"обычный: {'восстановлено' if r1.get('reasoning') == exp else 'в рассуждениях «' + str(r1.get('reasoning'))[:90] + '…»'}; стрим: {'восстановлено' if r2.get('reasoning') == exp else 'не восстановлено'}"


@case("TC-10", "Аргументы вызова инструмента (tool calls)", "исходные значения восстановлены в аргументах — обычный ответ и стрим")
def tc10(s):
    msgs = user(LETTER)
    exp = json.dumps({"text": expected_echo(msgs)}, ensure_ascii=False)
    r1 = s.chat("echo-tools", msgs)
    r2 = s.chat("echo-tools", msgs, stream=True)
    ok1 = r1.get("tool_args") == [exp]
    ok2 = r2.get("tool_args") == [exp]
    detail = lambda ok, r: "восстановлено" if ok else "«" + (r.get("tool_args") or ["—"])[0][:90] + "…»"
    return ok1 and ok2, f"обычный: {detail(ok1, r1)}; стрим: {detail(ok2, r2)}"


@case("TC-11", "Длинная история чата (41 сообщение, ~37 тыс. символов)", "добавочная задержка guardrail")
def tc11(s):
    base = PERSONAL + " " + "Подготовь служебную записку по итогам сентября. "
    msgs = []
    for _ in range(20):
        msgs += [{"role": "user", "content": base * 3}, {"role": "assistant", "content": "Принято."}]
    msgs.append({"role": "user", "content": "Итог?"})
    times = []
    for _ in range(3):
        r = s.chat("echo", msgs)
        times.append(r["t"])
    ok = r["status"] == 200 and r.get("text") == expected_echo(msgs)
    return ok, f"{min(times) * 1000:.0f} мс на запрос (лучшее из 3), ответ восстановлен: {r.get('text') == expected_echo(msgs)}"


@case("TC-12", "Название месторождения «Сухой Лог»", "не считается ПДн, если указано в allow-list")
def tc12(s):
    s.chat("echo", user("На месторождении Сухой Лог за сентябрь добыто 1520 кг."))
    sent = sent_texts(s.upstream_last())[-1]
    return "Сухой Лог" in sent, f"в модель: «{sent}»"


@case("TC-13", "presidio_language: ru", "pii-service принимает код языка ru")
def tc13(s):
    code, res = s.analyze("Звонил Петров Иван Сергеевич", language="ru")
    return code == 200 and bool(res), f"/analyze с language=ru: HTTP {code}" + (f", найдено {len(res)}" if res else "")


@case("TC-14", "pii-service недоступен", "запрос отклонён быстро, в модель ничего не ушло")
def tc14(s):
    if not s.project:
        return None, "пропущен: не задан --project"
    s.compose("stop", "pii-service")
    try:
        n = s.upstream_count()
        r = s.chat("echo", user("Привет! Как дела?"), timeout=60)
        ok = r["status"] in (500, 503) and s.upstream_count() == n and r["t"] < 5
        return ok, f"HTTP {r['status']} через {r['t']:.1f} с, дошло до модели: {s.upstream_count() - n}"
    finally:
        s.compose("start", "pii-service")
        for _ in range(60):
            if json.loads(s.compose("ps", "--format", "json", "pii-service").stdout.splitlines()[0]).get("Health") == "healthy":
                break
            time.sleep(2)


@case("TC-15", "Исходные ПДн в журналах LiteLLM и логах контейнеров", "не найдены")
def tc15(s):
    if not s.project:
        return None, "пропущен: не задан --project"
    count = lambda: s.compose("exec", "-T", "pg", "psql", "-U", "litellm", "-d", "litellm", "-tAc",
                              "select count(*) from \"LiteLLM_SpendLogs\"").stdout.strip()
    prev, stable = None, 0
    for _ in range(45):  # LiteLLM пишет журнал расходов пачками — ждём, пока он перестанет пополняться
        cur = count()
        stable = stable + 1 if cur == prev else 0
        if stable >= 6:
            break
        prev = cur
        time.sleep(5)
    found = []
    for o in ["Петров", "Сидоров", "i.petrov@example.ru", "2515 123456", "4111 1111", "sk-proj-7Hq2"]:
        q = (f"select count(*) from \"LiteLLM_SpendLogs\" where messages::text like '%{o}%' or response::text like '%{o}%' "
             f"or proxy_server_request::text like '%{o}%' or metadata::text like '%{o}%'")
        db = s.compose("exec", "-T", "pg", "psql", "-U", "litellm", "-d", "litellm", "-tAc", q).stdout.strip()
        logs = s.compose("logs", "litellm", "pii-service").stdout.count(o)
        if db not in ("0", "") or logs:
            found.append(f"{o}: журнал {db}, логи {logs}")
    rows = count()
    return not found, (f"записей в журнале: {rows}; " + ("исходных ПДн нет" if not found else "найдено: " + "; ".join(found)))


# ── кейсы с настоящими моделями ──────────────────────────────────────────────

def real_cases(s, models, repeat=1):
    out = []
    for m in [m for m in models for _ in range(repeat)]:
        r = s.chat(m, user(LETTER), stream=True, max_tokens=4000)
        if r["status"] != 200:
            out.append({"id": f"R-{m}", "model": m, "status": r["status"], "error": r.get("error")})
            continue
        text = (r.get("text") or "").strip()
        greet = next((ln.strip() for ln in text.splitlines() if "Уважаем" in ln), "")
        sign = [ln.strip() for ln in text.splitlines() if ln.strip()][-3:]
        out.append({"id": f"R-{m}", "model": m, "status": 200, "greeting": greet, "tail": sign,
                    "has_tokens": bool(re.search(r"[<\[][A-ZА-Я_\-a-zа-я]+_\d+[>\]]", text)),
                    "reasoning_tokens": bool(re.search(r"<[A-Z_]+_\d+>", r.get("reasoning") or "")),
                    "reasoning_len": len(r.get("reasoning") or ""), "chunks": r.get("chunks"),
                    "ttfb": r.get("ttfb"), "t": r["t"], "text": text})
    return out


# ── запуск и отчёт ───────────────────────────────────────────────────────────

def run(args):
    s = Stand(args)
    results = []
    for cid, title, check, fn in CASES:
        if args.only and cid not in args.only.split(","):
            continue
        try:
            ok, detail = fn(s)
        except Exception as e:
            ok, detail = False, f"ошибка кейса: {type(e).__name__}: {e}"
        mark = {True: "✅", False: "❌", None: "—"}[ok]
        print(f"{mark} {cid} {title}: {detail}", file=sys.stderr)
        results.append({"id": cid, "title": title, "check": check, "ok": ok, "detail": detail})
    real = real_cases(s, [m for m in (args.real_models or "").split(",") if m], args.real_repeat)
    for r in real:
        print(f"   {r['id']}: {r.get('greeting') or r.get('error')}", file=sys.stderr)
    json.dump({"label": args.label, "cases": results, "real": real}, open(args.out, "w"), ensure_ascii=False, indent=1)


def report(args):
    before, after = (json.load(open(p)) for p in (args.before, args.after))
    b = {c["id"]: c for c in before["cases"]}
    mark = {True: "✅", False: "❌", None: "—"}
    print("| Кейс | Что проверяем | Критерий | Было | Стало |\n|---|---|---|---|---|")
    for c in after["cases"]:
        old = b.get(c["id"], {"ok": None, "detail": "—"})
        cell = lambda x: f"{mark[x['ok']]} {x['detail']}".replace("|", "\\|").replace("\n", " ")
        print(f"| {c['id']} | {c['title']} | {c['check']} | {cell(old)} | {cell(c)} |")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", required=True)
    r.add_argument("--litellm", default="http://127.0.0.1:34000")
    r.add_argument("--pii", default="http://127.0.0.1:35001")
    r.add_argument("--log", default="log/after/upstream.jsonl")
    r.add_argument("--project", default="")
    r.add_argument("--real-models", default="")
    r.add_argument("--real-repeat", type=int, default=1)
    r.add_argument("--only", default="")
    r.add_argument("--out", required=True)
    p = sub.add_parser("report")
    p.add_argument("before")
    p.add_argument("after")
    a = ap.parse_args()
    run(a) if a.cmd == "run" else report(a)
