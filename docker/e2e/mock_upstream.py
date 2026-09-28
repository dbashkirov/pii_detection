"""Заглушка OpenAI-совместимой модели для e2e-проверки guardrail.

Каждый запрос, пришедший от LiteLLM, пишется в /log/upstream.jsonl — это ровно то, что ушло бы
в настоящую модель. Ответ — эхо: content всех не-system сообщений через « | ».

Модели:
  echo            — эхо в content;
  echo-reasoning  — эхо и в reasoning_content, и в content;
  echo-tools      — вызов инструмента, эхо в аргументах: {"text": "..."}.

stream=true: ответ режется по 7 символов (метки и ФИО попадают на границы чанков), 50 мс между чанками.
"""
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = "/log/upstream.jsonl"
CHUNK = 7
DELAY = 0.05


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def echo(req):
    return " | ".join(text_of(m.get("content")) for m in req.get("messages", []) if m.get("role") != "system")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json({"object": "list", "data": [{"id": m, "object": "model"} for m in ("echo", "echo-reasoning", "echo-tools")]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with open(LOG, "a") as f:
            f.write(json.dumps({"ts": time.time(), "body": req}, ensure_ascii=False) + "\n")
        model = req.get("model", "echo")
        text = echo(req)
        # id уникальный: по нему LiteLLM пишет журнал расходов, повторы там отбрасываются
        base = {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "created": int(time.time()), "model": model}
        usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}

        if not req.get("stream"):
            message = {"role": "assistant", "content": text}
            if model == "echo-reasoning":
                message["reasoning_content"] = text
            if model == "echo-tools":
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "save", "arguments": json.dumps({"text": text}, ensure_ascii=False)}}]}
            self._json({**base, "object": "chat.completion", "usage": usage, "choices": [
                {"index": 0, "message": message, "finish_reason": "tool_calls" if model == "echo-tools" else "stop"}]})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(delta, finish=None, extra=None):
            chunk = {**base, "object": "chat.completion.chunk",
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **(extra or {})}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        send({"role": "assistant", "content": ""})
        parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
        if model == "echo-tools":
            send({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                  "function": {"name": "save", "arguments": ""}}]})
            args = json.dumps({"text": text}, ensure_ascii=False)
            for i in range(0, len(args), CHUNK):
                send({"tool_calls": [{"index": 0, "function": {"arguments": args[i:i + CHUNK]}}]})
                time.sleep(DELAY)
            send({}, "tool_calls", {"usage": usage})
        else:
            if model == "echo-reasoning":
                for p in parts:
                    send({"reasoning_content": p})
                    time.sleep(DELAY)
            for p in parts:
                send({"content": p})
                time.sleep(DELAY)
            send({}, "stop", {"usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
