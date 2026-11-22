"""post_comment node: publish the review on the PR, and tell GitHub Actions how many bugs it found.

One review per run (pulls/{n}/reviews) with an inline comment per finding, or a short
"no issues found" review when there are none. DRY_RUN=true prints instead of posting.
The review is always a plain COMMENT: whether to merge is a human decision, enforced by
the workflow's `approval` job when bug_count > 0.
"""

import os
from collections import Counter

import config
import github_api
from state import ReviewComment, ReviewState

MARKER = "<!-- pr-review-agent -->"  # lets a later version find the agent's own reviews
SEVERITIES = ("bug", "warning", "nit")


def comment_body(c: ReviewComment) -> str:
    return f"**{c['severity'].capitalize()}:** {c['issue']}\n\n**Suggestion:** {c['suggestion']}"


def summary_line(comments: list[ReviewComment]) -> str:
    if not comments:
        return "No issues found."
    counts = Counter(c["severity"] for c in comments)
    parts = [f"{counts[s]} {s}{'s' if counts[s] > 1 else ''}" for s in SEVERITIES if counts[s]]
    return f"Found {len(comments)} issue{'s' if len(comments) > 1 else ''}: {', '.join(parts)}."


def review_body(comments: list[ReviewComment]) -> str:
    body = f"{MARKER}\n**PR review agent:** {summary_line(comments)}"
    if os.getenv("GITHUB_ACTIONS") and any(c["severity"] == "bug" for c in comments):
        body += "\n\nA maintainer must approve the `approval` check of this run before merging."
    return body


def build_review(comments: list[ReviewComment]) -> dict:
    review = {"event": "COMMENT", "body": review_body(comments)}
    if comments:
        review["comments"] = [
            {"path": c["path"], "line": c["line"], "side": "RIGHT", "body": comment_body(c)}
            for c in comments
        ]
    return review


def fallback_review(comments: list[ReviewComment]) -> dict:
    """Same findings in the review body, for when GitHub rejects an inline position (422)."""
    listed = "\n\n".join(f"`{c['path']}:{c['line']}`. {comment_body(c)}" for c in comments)
    return {"event": "COMMENT", "body": f"{review_body(comments)}\n\n{listed}"}


def report_to_actions(comments: list[ReviewComment]) -> None:
    """In GitHub Actions: expose bug_count as a step output and list findings in the run summary."""
    bugs = sum(c["severity"] == "bug" for c in comments)
    if out := os.getenv("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"bug_count={bugs}\n")
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        lines = [f"## PR review agent\n\n{summary_line(comments)}\n"]
        lines += [f"- **{c['severity']}** `{c['path']}:{c['line']}`: {c['issue']}" for c in comments]
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def print_review(review: dict) -> None:
    print(f"  {review['body'].replace(MARKER, '').strip()}")
    for c in review.get("comments", []):
        print(f"\n  inline comment on {c['path']}:{c['line']}")
        print("    " + c["body"].replace("\n", "\n    "))


def post_comment(state: ReviewState) -> dict:
    comments = state.get("final_comments", [])
    if config.eval_mode():  # evals score the comments from the state; nothing is printed or posted
        print(f"post_comment: EVAL_MODE, not posting; {len(comments)} final comment(s) left in the state")
        return {"final_comments": comments}

    repo, number = state["repo"], state["pr_number"]
    review = build_review(comments)

    if config.dry_run():
        print(f"post_comment: DRY_RUN, not posting. This review would go on {repo}#{number}:")
        print_review(review)
        report_to_actions(comments)
        return {}

    path = f"/repos/{repo}/pulls/{number}/reviews"
    with github_api.session() as s:
        try:
            posted = github_api.post(s, path, review, "posting the review")
        except github_api.GitHubError as e:
            if e.status != 422 or not comments:
                raise
            print(f"post_comment: GitHub rejected an inline position ({e}); posting the findings in the body")
            posted = github_api.post(s, path, fallback_review(comments), "posting the review (fallback)")
    print(f"post_comment: posted review with {len(comments)} finding(s): {posted.get('html_url')}")
    report_to_actions(comments)
    return {}
