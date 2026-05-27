import re


def validate_inn(s: str) -> bool:
    s = re.sub(r"\D", "", s)
    if len(s) == 10:
        weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        check = sum(int(s[i]) * weights[i] for i in range(9)) % 11 % 10
        return check == int(s[9])
    if len(s) == 12:
        w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c1 = sum(int(s[i]) * w1[i] for i in range(10)) % 11 % 10
        c2 = sum(int(s[i]) * w2[i] for i in range(11)) % 11 % 10
        return c1 == int(s[10]) and c2 == int(s[11])
    return False


def validate_snils(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if len(digits) != 11:
        return False
    weights = [9, 8, 7, 6, 5, 4, 3, 2, 1]
    total = sum(int(digits[i]) * weights[i] for i in range(9))
    remainder = total % 101
    checksum = 0 if remainder >= 100 else remainder
    return checksum == int(digits[9:11])


def validate_ogrn(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if len(digits) != 13:
        return False
    check = int(digits[:12]) % 11 % 10
    return check == int(digits[12])


def validate_ogrnip(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if len(digits) != 15:
        return False
    check = int(digits[:14]) % 13 % 10
    return check == int(digits[14])


def validate_luhn(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if not digits:
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
