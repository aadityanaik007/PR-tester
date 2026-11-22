"""Load an eval case and run the real review graph on it offline.

No GitHub calls, no posting: the diff comes from the case's diff.patch, retrieve indexes
the case's before/ snapshot, and EVAL_MODE makes post_comment leave the final comments
in the state.

    uv run evals/harness.py 01_discount_rate_cross_file
"""

import json
import os
import sys
from pathlib import Path

REVIEWER_DIR = Path(__file__).resolve().parents[1]
if str(REVIEWER_DIR) not in sys.path:
    sys.path.insert(0, str(REVIEWER_DIR))

from diff_utils import split_unified_diff  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"


def case_ids() -> list[str]:
    return sorted(p.name for p in CASES_DIR.iterdir() if p.is_dir())


def load_case(case_id: str) -> dict:
    """{"inputs": {"case_id", "files"}, "outputs": expected.json}, the shape of a dataset example."""
    case = CASES_DIR / case_id
    return {
        "inputs": {
            "case_id": case_id,
            "files": split_unified_diff((case / "diff.patch").read_text(encoding="utf-8")),
        },
        "outputs": json.loads((case / "expected.json").read_text(encoding="utf-8")),
    }


def run_case(inputs: dict, graph=None) -> dict:
    """Run the graph on one case. The index folder is derived from case_id, so dataset
    inputs stay portable (no machine-specific paths)."""
    os.environ["EVAL_MODE"] = "true"
    if graph is None:
        from graph import build_graph
        graph = build_graph()
    state = {
        "repo": "eval/offline",
        "pr_number": 0,
        "files": inputs["files"],
        "index_dir": str(CASES_DIR / inputs["case_id"] / "before"),
    }
    out = graph.invoke(state, config={"run_name": f"eval {inputs['case_id']}"})
    return {
        "comments": out.get("final_comments", []),
        "draft_comments": out.get("draft_comments", []),
        "attempts": out.get("attempts", 0),
    }


if __name__ == "__main__":
    case = load_case(sys.argv[1] if len(sys.argv) > 1 else case_ids()[0])
    result = run_case(case["inputs"])
    print("\n=== final comments ===")
    print(json.dumps(result["comments"], indent=2))
