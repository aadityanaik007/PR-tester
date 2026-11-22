"""verifier node: a second Claude call checks each draft comment and drops weak ones.

Sees the same numbered diff and retrieved code as the reviewer, plus the drafts. Keeps a
comment only if it is specific and the code supports it; may lower an overstated severity
(a "bug" blocks the merge until a human approves). needs_retry is set only when there
were drafts and every one was rejected.
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from llm import chat_model, render_files
from state import ReviewComment, ReviewState

SYSTEM = """\
You check another reviewer's comments on a GitHub pull request before they are posted. \
You get each changed file's diff, with line numbers for the new version, the related \
code from elsewhere in the repository that the reviewer saw, and the numbered draft \
comments.

Keep a comment only if the problem is real, the diff or the related code shows it, and \
the comment is specific: it names the code involved and what goes wrong. Drop comments \
that are vague, speculative, contradicted by the code, or that the code doesn't support. \
If a kept comment overstates its impact, give it the lower severity it deserves: "bug" \
breaks or gives wrong results, "warning" is risky or likely wrong, "nit" is minor. \
Give one verdict per draft comment."""


class Verdict(BaseModel):
    index: int = Field(description="The draft comment's number, as listed.")
    keep: bool
    severity: Literal["bug", "warning", "nit"] = Field(
        description="Severity to post with; lower than the draft's if it overstates the impact."
    )
    reason: str = Field(description="One sentence: why it is kept or dropped, citing the code.")


class Verification(BaseModel):
    verdicts: list[Verdict]


def render_drafts(drafts: list[ReviewComment]) -> str:
    return "\n\n".join(
        f"{i}. {c['path']}:{c['line']} [{c['severity']}]\n"
        f"   issue: {c['issue']}\n   suggestion: {c['suggestion']}"
        for i, c in enumerate(drafts, 1)
    )


def verifier(state: ReviewState) -> dict:
    drafts = state.get("draft_comments", [])
    if not drafts:
        print("verifier: no draft comments to check")
        return {"final_comments": [], "needs_retry": False}

    prompt = (
        render_files(state.get("files", []), state.get("context", {}))
        + "\n\n## Draft comments to check\n\n"
        + render_drafts(drafts)
    )
    model = chat_model(effort="high").with_structured_output(Verification, method="json_schema", include_raw=True)
    result = model.invoke([SystemMessage(SYSTEM), HumanMessage(prompt)])
    verification: Verification | None = result["parsed"]
    if verification is None:
        stop = result["raw"].response_metadata.get("stop_reason")
        raise RuntimeError(f"verifier: no structured verdicts (stop_reason={stop}): {result['parsing_error']}")

    verdicts = {v.index: v for v in verification.verdicts}
    kept: list[ReviewComment] = []
    print(f"verifier: checked {len(drafts)} draft(s)")
    for i, c in enumerate(drafts, 1):
        v = verdicts.get(i)
        if v is None:
            print(f"  drop #{i} {c['path']}:{c['line']}  (no verdict returned, treated as unsupported)")
            continue
        severity = v.severity if v.keep else c["severity"]
        change = f" {c['severity']}->{severity}" if v.keep and severity != c["severity"] else ""
        print(f"  {'keep' if v.keep else 'drop'} #{i} {c['path']}:{c['line']} [{severity}]{change}  {v.reason}")
        if v.keep:
            kept.append({**c, "severity": severity})

    return {"final_comments": kept, "needs_retry": not kept}
