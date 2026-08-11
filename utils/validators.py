import re

from email_validator import validate_email, EmailNotValidError

def is_valid_name(name: str) -> bool:
    name = name.strip()
    parts = name.split()
    return (
        len(parts) >= 2
        and all(re.fullmatch(r"[A-Za-z'\-]+", part) for part in parts)
    )

def is_valid_email(email: str) -> bool:
    try:
        validate_email(email, check_deliverability=True)
        return True
    except EmailNotValidError:
        return False


def is_valid_phone(phone: str) -> bool:
    phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("+"):
        phone = phone[1:]

    return phone.isdigit() and 10 <= len(phone) <= 15

def is_valid_experience(exp: str) -> bool:
    exp = exp.replace("+", "").strip()
    try:
        val = float(exp)
        return val >= 0
    except ValueError:
        return False