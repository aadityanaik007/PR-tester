"""Entry point: builds a sample order and prints the receipt."""

from service import build_receipt


def main() -> None:
    items = [
        {"name": "Notebook", "price": 4.50, "quantity": 3},
        {"name": "Pen", "price": 1.25, "quantity": 10},
        {"name": "Backpack", "price": 39.99, "quantity": 1},
    ]
    print(build_receipt(items, discount_percent=10))


if __name__ == "__main__":
    main()