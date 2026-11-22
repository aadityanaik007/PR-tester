"""
PR review agent: wiring only. Each node lives in nodes/<name>.py.

    fetch_diff -> retrieve -> reviewer -> verifier -> post_comment
                                  ^           |
                                  +-----------+  retry if the verifier rejected everything

Run:  uv run graph.py                      (target from GITHUB_REPOSITORY / PR_NUMBER)
      uv run graph.py --repo o/r --pr 1    (fallback when those env vars are unset)
"""

from dotenv import load_dotenv

# Load .env before anything reads the environment (LANGSMITH_*, GITHUB_TOKEN,
# ANTHROPIC_API_KEY). Real env vars win over .env, so CI settings take priority.
load_dotenv()

from langgraph.graph import END, START, StateGraph  # noqa: E402

from config import get_target  # noqa: E402
from nodes import fetch_diff, post_comment, retrieve, reviewer, verifier  # noqa: E402
from state import ReviewState  # noqa: E402

MAX_ATTEMPTS = 2


def after_verify(state: ReviewState) -> str:
    """Send work back to the reviewer once if the verifier rejected everything."""
    if state.get("needs_retry") and state.get("attempts", 0) < MAX_ATTEMPTS:
        return "reviewer"
    return "post_comment"


def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("fetch_diff", fetch_diff)
    g.add_node("retrieve", retrieve)
    g.add_node("reviewer", reviewer)
    g.add_node("verifier", verifier)
    g.add_node("post_comment", post_comment)

    g.add_edge(START, "fetch_diff")
    g.add_edge("fetch_diff", "retrieve")
    g.add_edge("retrieve", "reviewer")
    g.add_edge("reviewer", "verifier")
    g.add_conditional_edges("verifier", after_verify, ["reviewer", "post_comment"])
    g.add_edge("post_comment", END)
    return g.compile()


if __name__ == "__main__":
    repo, pr_number = get_target()
    app = build_graph()
    # One invoke = one LangSmith trace; the nodes show up as child runs.
    app.invoke(
        {"repo": repo, "pr_number": pr_number},
        config={
            "run_name": "pr-review",
            "tags": ["pr-reviewer", "v2"],
            "metadata": {"repo": repo, "pr_number": pr_number},
        },
    )
