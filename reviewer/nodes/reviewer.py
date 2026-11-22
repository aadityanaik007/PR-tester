"""reviewer node: Claude reviews the diff plus retrieved context and returns structured comments."""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from diff_utils import commentable_lines
from llm import chat_model, render_files
from state import ReviewComment, ReviewState

SYSTEM = """\
You review GitHub pull requests. For each changed file you get its diff, with line \
numbers for the new version, and code from elsewhere in the repository that calls or \
resembles the changed functions.

Find real problems this change introduces: bugs, broken callers, wrong results, security \
issues. A change can look correct on its own and still break code outside the diff, so \
check the related code against the new behavior.

Each comment must sit on a numbered line of a changed file. When the breakage is in \
another file, put the comment on the changed line that causes it and name the affected \
file, function and line in the issue.

Severity: "bug" breaks or gives wrong results; "warning" is risky or likely wrong; \
"nit" is minor or style. Only report what the diff and the related code support. \
If nothing is wrong, return no comments."""

RETRY_NOTE = """

A previous review of this PR was rejected: a second reviewer found every comment below \
vague, unsupported by the code, or wrong. Don't repeat them unless the code clearly \
supports them; returning no comments is fine.

{previous}"""


class CommentOut(BaseModel):
    path: str = Field(description="The changed file, exactly as written after '## Changed file:'.")
    line: int = Field(description="A numbered line from that file's diff.")
    severity: Literal["bug", "warning", "nit"]
    issue: str = Field(description="What goes wrong and why, citing the specific code.")
    suggestion: str = Field(description="The concrete fix.")


class ReviewOut(BaseModel):
    comments: list[CommentOut]


def reviewer(state: ReviewState) -> dict:
    attempts = state.get("attempts", 0) + 1
    files = state.get("files", [])
    if not files:
        print("reviewer: no reviewable files")
        return {"draft_comments": [], "attempts": attempts}

    prompt = render_files(files, state.get("context", {}))
    if attempts > 1 and state.get("draft_comments"):
        previous = "\n".join(
            f"- {c['path']}:{c['line']} [{c['severity']}] {c['issue']}" for c in state["draft_comments"]
        )
        prompt += RETRY_NOTE.format(previous=previous)

    model = chat_model(effort="high").with_structured_output(ReviewOut, method="json_schema", include_raw=True)
    result = model.invoke([SystemMessage(SYSTEM), HumanMessage(prompt)])
    review: ReviewOut | None = result["parsed"]
    if review is None:
        stop = result["raw"].response_metadata.get("stop_reason")
        raise RuntimeError(f"reviewer: no structured review (stop_reason={stop}): {result['parsing_error']}")

    # GitHub rejects inline comments outside the diff, so drop any that miss.
    allowed = {f["path"]: commentable_lines(f["diff"]) for f in files}
    comments: list[ReviewComment] = []
    for c in review.comments:
        if c.line in allowed.get(c.path, set()):
            comments.append(c.model_dump())
        else:
            print(f"  dropped (not a commentable diff line): {c.path}:{c.line} {c.issue[:80]}")

    print(f"reviewer (attempt {attempts}): {len(comments)} comment(s)")
    for c in comments:
        print(f"  [{c['severity']}] {c['path']}:{c['line']}  {c['issue']}")
    return {"draft_comments": comments, "attempts": attempts}
