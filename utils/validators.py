import re

def is_valid_name(name: str) -> bool:
    name = name.strip()
    parts = name.split()
    return (
        len(parts) >= 2
        and all(part.isalpha() for part in parts)
    )

def is_valid_email(email: str) -> bool:
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    return re.match(pattern, email) is not None

def is_valid_phone(phone: str) -> bool:
    phone = phone.replace(" ", "").replace("-", "")
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
