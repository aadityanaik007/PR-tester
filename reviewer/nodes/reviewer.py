"""reviewer node: Claude reviews the diff plus retrieved context and returns structured comments.

A ReAct loop: Claude may call lookup tools (PyPI, OSV, Wikipedia) and read the results,
for up to MAX_TOOL_ROUNDS rounds, then answers with the structured review. The review
format is enforced on every call (output_config.format), so no extra request is needed
when Claude uses no tools.
"""

import json
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field, ValidationError

from diff_utils import commentable_lines
from llm import chat_model, render_files
from state import ReviewComment, ReviewState
from tools import TOOLS, TOOLS_BY_NAME

MAX_TOOL_ROUNDS = 5

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
If nothing is wrong, return no comments.

You have lookup tools for facts the code can't show: whether a package or version exists \
on PyPI, known vulnerabilities for a pinned version (OSV), and the definition of a named \
algorithm or standard (Wikipedia). Use them when a comment would depend on such a fact; \
most reviews need none."""

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


def run_tool(call: dict) -> ToolMessage:
    """Run one tool call; any failure goes back to Claude as the tool's result."""
    tool = TOOLS_BY_NAME.get(call["name"])
    try:
        if tool is None:
            raise ValueError(f"unknown tool {call['name']!r}")
        msg = tool.invoke(call)  # a ToolCall in -> a ToolMessage out, traced as a tool run
    except Exception as e:  # noqa: BLE001 - bad arguments etc. are for Claude to fix
        msg = ToolMessage(content=f"Tool error: {e}", tool_call_id=call["id"], status="error")
    first_line = str(msg.content).splitlines()[0] if msg.content else ""
    print(f"  tool {call['name']}({json.dumps(call['args'])}) -> {first_line[:100]}")
    return msg


def run_agent(messages: list[BaseMessage]) -> ReviewOut:
    """ReAct loop: Claude reasons, optionally calls tools, reads results, then returns the review."""
    llm = chat_model(effort="high").bind_tools(TOOLS, response_format=ReviewOut)
    for round_no in range(1, MAX_TOOL_ROUNDS + 2):
        ai = llm.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            break
        if round_no > MAX_TOOL_ROUNDS:
            raise RuntimeError(f"reviewer: still calling tools after {MAX_TOOL_ROUNDS} rounds")
        messages.extend(run_tool(call) for call in ai.tool_calls)
        if round_no == MAX_TOOL_ROUNDS:
            messages.append(HumanMessage("Tool budget used up. Give your final review now, without calling tools."))

    stop = ai.response_metadata.get("stop_reason")
    try:
        return ReviewOut.model_validate_json(ai.text)
    except ValidationError as e:
        raise RuntimeError(f"reviewer: no structured review (stop_reason={stop}): {e}") from e


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

    review = run_agent([SystemMessage(SYSTEM), HumanMessage(prompt)])

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
