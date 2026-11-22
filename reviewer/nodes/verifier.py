"""verifier node (stub): drops nits, keeps the rest."""

from state import ReviewState


def verifier(state: ReviewState) -> dict:
    """TODO: second LLM checks each comment against the code and drops weak ones."""
    kept = [c for c in state["draft_comments"] if c["severity"] != "nit"]
    return {"final_comments": kept, "needs_retry": len(kept) == 0}
