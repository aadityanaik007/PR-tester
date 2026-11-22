"""Small helper functions used by the order service."""


def apply_discount(amount: float, rate: float) -> float:
    """Apply a discount rate. rate=0.1 means 10% off."""
    if rate < 0 or rate > 1:
        raise ValueError("rate must be between 0 and 1")
    return round(amount * (1 - rate), 2)


def calculate_tax(amount: float, rate: float = 0.08) -> float:
    """Return the tax owed on an amount."""
    return round(amount * rate, 2)


def format_currency(amount: float) -> str:
    """Format a number as US dollars, e.g. 1234.5 -> $1,234.50."""
    return f"${amount:,.2f}"