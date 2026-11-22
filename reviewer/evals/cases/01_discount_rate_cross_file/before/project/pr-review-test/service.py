"""Order logic. Depends on the helpers in utils.py."""

from utils import apply_discount, calculate_tax, format_currency


def calculate_subtotal(items: list[dict]) -> float:
    """Sum price * quantity for every item in the order."""
    return round(sum(item["price"] * item["quantity"] for item in items), 2)


def calculate_total(items: list[dict], discount_percent: float = 0) -> dict:
    """Return a breakdown of the order: subtotal, discount, tax and total."""
    subtotal = calculate_subtotal(items)
    discounted = apply_discount(subtotal, discount_percent)
    tax = calculate_tax(discounted)
    return {
        "subtotal": subtotal,
        "discount": round(subtotal - discounted, 2),
        "tax": tax,
        "total": round(discounted + tax, 2),
    }


def build_receipt(items: list[dict], discount_percent: float = 0) -> str:
    """Build a printable receipt for an order."""
    lines = [
        f"{item['name']} x{item['quantity']}: "
        f"{format_currency(item['price'] * item['quantity'])}"
        for item in items
    ]
    totals = calculate_total(items, discount_percent)
    lines.append(f"Subtotal: {format_currency(totals['subtotal'])}")
    lines.append(f"Discount: -{format_currency(totals['discount'])}")
    lines.append(f"Tax: {format_currency(totals['tax'])}")
    lines.append(f"Total: {format_currency(totals['total'])}")
    return "\n".join(lines)