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
        # check_deliverability=False: this should be a fast, reliable, in-process
        # format check, not a live DNS/MX lookup on every signup and every resume
        # confirmation. Deliverability checking only confirms the domain has some
        # mail-accepting DNS record — it doesn't verify the actual mailbox exists
        # (that needs a real SMTP handshake) — so the correctness value it adds is
        # marginal next to the latency and DNS-as-a-single-point-of-failure cost.
        validate_email(email, check_deliverability=False)
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