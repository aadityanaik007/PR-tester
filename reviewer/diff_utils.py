"""Helpers for GitHub unified-diff patches (the `patch` field of a PR file).

Works from the patch alone, not the file on disk: locally the checkout is usually
the base branch while the patch describes the head, so disk line numbers can't be trusted.
"""

import re
from dataclasses import dataclass

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
DEF_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)")
# Lines at column 0 that do NOT end the enclosing def/class.
NOT_MODULE_LEVEL = ("@", "#", ")", "]", "}")


@dataclass
class DiffLine:
    kind: str              # "+" added, "-" removed, " " context
    text: str              # the line without its +/-/space prefix
    old_no: int | None     # line number in the base file (None for added lines)
    new_no: int | None     # line number in the head file (None for removed lines)
    symbol: str | None     # enclosing def/class name, best effort


def parse_patch(patch: str) -> list[DiffLine]:
    """Walk a patch, tracking line numbers and which def/class each line sits in."""
    out: list[DiffLine] = []
    old_no = new_no = 0
    symbol: str | None = None
    for raw in patch.splitlines():
        if m := HUNK_RE.match(raw):
            old_no, new_no = int(m[1]), int(m[2])
            # git puts the enclosing def/class after the second @@ when the hunk starts inside one
            ctx = DEF_RE.match(m[3])
            symbol = ctx[1] if ctx else None
            continue
        if not raw or raw[0] not in "+- ":
            continue  # e.g. "\ No newline at end of file"
        kind, text = raw[0], raw[1:]
        if d := DEF_RE.match(text):
            symbol = d[1]
        elif text.strip() and not text[0].isspace() and not text.startswith(NOT_MODULE_LEVEL):
            symbol = None  # back at module level
        out.append(DiffLine(
            kind=kind,
            text=text,
            old_no=old_no if kind != "+" else None,
            new_no=new_no if kind != "-" else None,
            symbol=symbol,
        ))
        if kind != "+":
            old_no += 1
        if kind != "-":
            new_no += 1
    return out


def changed_symbols(patch: str) -> dict[str, str]:
    """Functions/classes with at least one added or removed line -> their code from the patch.

    The code is the new-side view (context + added lines). For a function that was only
    deleted, it falls back to the removed lines so there is still something to search with.
    """
    lines = parse_patch(patch)
    touched = {ln.symbol for ln in lines if ln.kind != " " and ln.symbol and ln.text.strip()}
    result: dict[str, str] = {}
    for name in sorted(touched):
        new_side = [ln.text for ln in lines if ln.symbol == name and ln.kind != "-"]
        if not any(t.strip() for t in new_side):
            new_side = [ln.text for ln in lines if ln.symbol == name]
        result[name] = "\n".join(new_side)
    return result


def new_side_code(patch: str) -> str:
    """All context + added lines, for files where no def/class could be identified."""
    return "\n".join(ln.text for ln in parse_patch(patch) if ln.kind != "-")
