"""reviewer node (stub): returns a hard-coded comment."""

from state import ReviewState


def reviewer(state: ReviewState) -> dict:
    """TODO: call the LLM with diff + context, return structured comments."""
    comments = [
        {
            "path": "utils.py",
            "line": 4,
            "severity": "bug",
            "issue": "apply_discount now expects a 0 to 1 rate, but service.py "
                     "still passes a percentage like 10, so orders will raise ValueError.",
            "suggestion": "Update calculate_total to pass discount_percent / 100.",
        }
    ]
    return {"draft_comments": comments, "attempts": state.get("attempts", 0) + 1}
