"""Money formatting helpers shared by both bots."""


def format_money(amount: float) -> str:
    """Format a ruble amount as "1 234,56 ₽"."""
    amount = round(float(amount) + 1e-9, 2)
    if amount == 0:
        amount = 0.0
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    whole = int(amount)
    frac = round((amount - whole) * 100)
    if frac == 100:
        whole += 1
        frac = 0
    whole_str = f"{whole:,}".replace(",", " ")
    return f"{sign}{whole_str},{frac:02d} ₽"


def format_shares(amount) -> str:
    amount = int(amount)
    return f"{amount:,}".replace(",", " ")


def format_percent(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}%".replace(".", ",")


def format_signed_percent(value: float, digits: int = 2) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{format_percent(value, digits)}"
