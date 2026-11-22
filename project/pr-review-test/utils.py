"""Small helper functions used by the order service."""


def apply_discount(amount: float, percent: float) -> float:
    """Apply a percentage discount. percent=10 means 10% off."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(amount * (1 - percent / 100), 2)


def calculate_tax(amount: float, rate: float = 0.08) -> float:
    """Return the tax owed on an amount."""
    return round(amount * rate, 2)


def format_currency(amount: float) -> str:
    """Format a number as US dollars, e.g. 1234.5 -> $1,234.50."""
    return f"${amount:,.2f}"