"""Ложные срабатывания TOKEN и CVC на обычном тексте и то, что находиться обязано.

Ложные — по мотивам запросов, которые фильтр отклонял на проде: годы рядом с «кодексом», номера
ГОСТ и моделей техники, «оборот компании», пути модулей в Python-коде.

Нужен presidio-analyzer — проще всего в образе pii-service:
    docker run --rm -v "$PWD:/src" -w /src -e PYTHONPATH=/src <образ pii-service> \
        sh -c 'pip install -q pytest && python -m pytest -q tests/test_recognizers.py'
"""
import pytest

from pii_detector.recognizers.detectors import CvcRecognizer
from pii_detector.recognizers.token import TokenRecognizer

TOKEN = TokenRecognizer()
CVC = CvcRecognizer()


def found(recognizer, entity, text):
    return [text[r.start:r.end] for r in recognizer.analyze(text, [entity])]


@pytest.mark.parametrize("text", [
    "Какие изменения в Налоговом кодексе с 2026 года касаются НДПИ?",
    "Трудовой кодекс РФ, статья 1234",
    "Код ошибки 5003 при выгрузке из 1С",
    "Напиши Python code для отчёта за 2025 год",
    "Проверь пинг до сервера, задержка 1500 мс",
    "Базовый стандарт — ГОСТ Р 58761-2019, он упоминается в Градостроительном кодексе",
    "Постановление Госкомстата РФ от 05.01.2004 № 1 — коды в табеле учёта рабочего времени",
    "Система менеджмента: ISO 9001 у изготовителя — как подтверждение стабильности",
    "Двигатель КАМАЗ, модель 43118. Напиши код для документа Word",
    "Код подтверждения действует до 2026 года",
    "from openpyxl.worksheet.datavalidation import DataValidation",
    "def calculate_total_revenue_by_region(df):",
    "В заключение: логика в app/services/notifications/email_sender.py",
    "Включите параметр SQLALCHEMY_ENGINE_OPTIONS_POOL_RECYCLE в конфиге",
])
def test_token_ignores_ordinary_text(text):
    assert found(TOKEN, "TOKEN", text) == []


@pytest.mark.parametrize("text, value", [
    ("Ваш код подтверждения: 482913", "482913"),
    ("Код из СМС 4829, никому не сообщайте", "4829"),
    ("Your verification code is 4829", "4829"),
    ("пин-код 1234", "1234"),
    ("PIN 7788", "7788"),
    ("OTP: 55667788", "55667788"),
    ("Пароль от Wi-Fi 12345678", "12345678"),
    ("Код доступа к сейфу 3141", "3141"),
    ("Пришёл код 104729 для восстановления аккаунта", "104729"),
    ("api key: AbCdEf1234567890GhIjKlMnOpQrSt", "AbCdEf1234567890GhIjKlMnOpQrSt"),
    ("token: CorrectHorseBatteryStaple", "CorrectHorseBatteryStaple"),
    ("вот строка xK9mP2qL7vN4wR8tY3bF6hJ1cD5gS0aZ из конфига", "xK9mP2qL7vN4wR8tY3bF6hJ1cD5gS0aZ"),
    ("AQVN1HHJReSrfo9jU3aopsXrJyfQ_PuXabcd", "AQVN1HHJReSrfo9jU3aopsXrJyfQ_PuXabcd"),
    ("ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"),
])
def test_token_finds_secrets(text, value):
    assert value in found(TOKEN, "TOKEN", text)


@pytest.mark.parametrize("text", [
    "Оборот компании за 2025 год вырос на 12%",
    "Размер шин 315/80R22.5, обороты двигателя 1900",
    "Оборот персональных данных: УК РФ, ст. 272.1, введена в 2024 г.",
    "Ответ — три цифры после запятой: 0,125",
    "Записка на обратной стороне листа, кабинет 214",
    "Трёхзначный код региона на номере — 138",
])
def test_cvc_ignores_ordinary_text(text):
    assert found(CVC, "CVC", text) == []


@pytest.mark.parametrize("text, value", [
    ("CVC 123", "123"),
    ("CVV2: 456", "456"),
    ("код безопасности 789", "789"),
    ("Три цифры на обороте карты: 321", "321"),
    ("Карта 4111 1111 1111 1111, на обратной стороне 654", "654"),
    ("Активирую новую кредитную карту в мобильном приложении банка, просят код подтверждения 417", "417"),
    ("Просят трёхзначный код с обратной стороны: 902", "902"),
])
def test_cvc_finds_codes(text, value):
    assert value in found(CVC, "CVC", text)
