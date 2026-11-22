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


HUNK_COUNTS_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def split_unified_diff(text: str) -> list[dict]:
    """Split a multi-file unified diff (e.g. diff.patch) into [{"path", "diff"}], where each
    "diff" is hunks only, the same shape as the `patch` field GitHub returns per PR file.

    Hunk bodies are read by the line counts in their @@ header, so a removed line that
    happens to start with "--" can never be mistaken for a file header.
    """
    files: list[dict] = []
    path: str | None = None
    hunks: list[str] = []
    old_left = new_left = 0
    lines = text.splitlines()

    def flush() -> None:
        if path and hunks:
            files.append({"path": path, "diff": "\n".join(hunks)})

    for i, line in enumerate(lines):
        if old_left > 0 or new_left > 0:  # inside a hunk body
            hunks.append(line)
            tag = line[:1]
            if tag == "-":
                old_left -= 1
            elif tag == "+":
                new_left -= 1
            elif tag != "\\":  # context line (or an empty one with its space stripped)
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("\\") and hunks:  # "\ No newline at end of file" after a hunk
            hunks.append(line)
        elif m := HUNK_COUNTS_RE.match(line):
            hunks.append(line)
            old_left = int(m[1]) if m[1] is not None else 1
            new_left = int(m[2]) if m[2] is not None else 1
        elif line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            flush()
            hunks = []
            old, new = line[4:].split("\t")[0], lines[i + 1][4:].split("\t")[0]
            target = new if new != "/dev/null" else old  # a deleted file keeps its old path
            path = target[2:] if target.startswith(("a/", "b/")) else target
        # anything else ("diff --git", "index ...", the "+++" header line) is metadata
    flush()
    return files


def commentable_lines(patch: str) -> set[int]:
    """New-side line numbers GitHub accepts an inline comment on: added and context lines."""
    return {ln.new_no for ln in parse_patch(patch) if ln.new_no is not None}


def annotate(patch: str) -> str:
    """The patch with each added/context line prefixed by its line number in the new file.

    Removed lines and hunk headers get no number: they can't take an inline comment.
    """
    out: list[str] = []
    new_no = 0
    for raw in patch.splitlines():
        if m := HUNK_RE.match(raw):
            new_no = int(m[2])
            out.append(f"     {raw}")
        elif raw.startswith(("+", " ")):
            out.append(f"{new_no:>4} {raw}")
            new_no += 1
        else:  # removed line or "\ No newline at end of file"
            out.append(f"     {raw}")
    return "\n".join(out)
