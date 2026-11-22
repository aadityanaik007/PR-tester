"""retrieve node (stub): returns a hard-coded context snippet."""

from state import ReviewState


def retrieve(state: ReviewState) -> dict:
    """TODO: search the vector store and a name index for related code."""
    context = {
        f["path"]: [
            "service.py: discounted = apply_discount(subtotal, discount_percent)"
        ]
        for f in state["files"]
    }
    return {"context": context}
