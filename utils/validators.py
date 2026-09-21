from email_validator import validate_email, EmailNotValidError

def is_valid_name(name: str) -> bool:
    name = name.strip()
    if not name or len(name) > 120:  # matches Candidate.name's DB column limit
        return False
    parts = name.split()
    if not parts:
        return False
    for part in parts:
        # str.isalpha() is Unicode-aware (correctly accepts "José", "François",
        # "Müller", etc.), unlike the old [A-Za-z] pattern. Apostrophes, hyphens, and
        # periods are allowed within a part too — "O'Brien", "Anne-Marie", "K.", "J.R."
        stripped = part.replace("'", "").replace("-", "").replace(".", "")
        if not stripped or not stripped.isalpha():
            return False
    return True

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