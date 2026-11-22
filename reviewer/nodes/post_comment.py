"""post_comment node (stub): prints the final comments."""

from state import ReviewState


def post_comment(state: ReviewState) -> dict:
    """TODO: post inline comments on the PR via the GitHub API."""
    for c in state.get("final_comments", []):
        print(f"[{c['severity']}] {c['path']}:{c['line']}  {c['issue']}")
        print(f"    suggestion: {c['suggestion']}")
    return {}
