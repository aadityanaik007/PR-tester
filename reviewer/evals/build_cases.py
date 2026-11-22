"""Generate eval case folders under evals/cases/ from project/pr-review-test.

Each case gets:
  before/project/pr-review-test/   snapshot of the code (mirrors the repo layout, so paths
                                   match what a real PR would show)
  diff.patch                       the change under review, as a multi-file unified diff
  expected.json                    what a good review should (or should not) flag

The generated folders are the source of truth once written; this script won't overwrite
an existing case unless you pass --force.

    uv run evals/build_cases.py [--force]
"""

import difflib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "project" / "pr-review-test"
CASES_DIR = Path(__file__).resolve().parent / "cases"
REL = "project/pr-review-test"  # path prefix inside before/ and in the patch


def base(name: str) -> str:
    """A file from the base snapshot, with normalized line endings."""
    return (SRC / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"expected exactly one match for:\n{old}"
    return text.replace(old, new)


def write_case(case_id: str, changes: dict[str, str | None], expected: dict,
               extra_before: dict[str, str] | None = None, force: bool = False) -> None:
    """changes: file name -> new content (None deletes it). extra_before: files to add to the snapshot."""
    case = CASES_DIR / case_id
    if case.exists():
        if not force:
            print(f"  skip  {case_id} (exists; --force to regenerate)")
            return
        shutil.rmtree(case)

    before = case / "before" / REL
    before.mkdir(parents=True)
    for src in sorted(SRC.glob("*.py")):
        (before / src.name).write_text(base(src.name), encoding="utf-8", newline="\n")
    for name, content in (extra_before or {}).items():
        (before / name).write_text(content, encoding="utf-8", newline="\n")

    patch: list[str] = []
    for name, new in changes.items():
        old_file = before / name
        old_lines = old_file.read_text(encoding="utf-8").splitlines(keepends=True) if old_file.exists() else []
        new_lines = new.splitlines(keepends=True) if new is not None else []
        a = f"a/{REL}/{name}" if old_lines else "/dev/null"
        b = f"b/{REL}/{name}" if new is not None else "/dev/null"
        patch.append(f"diff --git a/{REL}/{name} b/{REL}/{name}\n")
        patch.extend(difflib.unified_diff(old_lines, new_lines, fromfile=a, tofile=b, n=3))

    (case / "diff.patch").write_text("".join(patch), encoding="utf-8", newline="\n")
    (case / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"  wrote {case_id}")


# ---------------------------------------------------------------------------- cases

APPLY_DISCOUNT_PERCENT = '''def apply_discount(amount: float, percent: float) -> float:
    """Apply a percentage discount. percent=10 means 10% off."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(amount * (1 - percent / 100), 2)
'''


def case_01(force: bool) -> None:
    """The original PR: apply_discount takes a 0-1 rate; service.py still passes a percentage."""
    utils = replace_once(base("utils.py"), APPLY_DISCOUNT_PERCENT, '''def apply_discount(amount: float, rate: float) -> float:
    """Apply a discount rate. rate=0.1 means 10% off."""
    if rate < 0 or rate > 1:
        raise ValueError("rate must be between 0 and 1")
    return round(amount * (1 - rate), 2)
''')
    write_case("01_discount_rate_cross_file", {"utils.py": utils}, {
        "should_flag": True,
        "issues": [{
            "path": f"{REL}/utils.py",
            "line_range": [4, 8],
            "keywords": ["calculate_total", "service.py", "percent", "ValueError"],
            "severity": "bug",
            "description": "apply_discount now takes a 0-1 rate, but service.py calculate_total still "
                           "passes discount_percent unchanged (main.py passes 10), so any discounted "
                           "order raises ValueError; percentages of 1 or less are silently misapplied.",
        }],
    }, force=force)


CASES = [case_01]

if __name__ == "__main__":
    force = "--force" in sys.argv
    print(f"building cases in {CASES_DIR}")
    for make in CASES:
        make(force)
