"""fetch_diff node: the PR's changed files and their patches, from the GitHub REST API."""

from pathlib import PurePosixPath

import github_api
from state import ChangedFile, ReviewState

MAX_CHANGED_LINES = 500

LOCKFILES = {
    "uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock",
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum", "packages.lock.json",
}

# GitHub omits `patch` for binary files; this list is a backstop for the obvious ones.
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf",
    ".zip", ".gz", ".tar", ".7z", ".whl", ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".bin", ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".mov",
    ".parquet", ".pkl", ".db", ".sqlite",
}


def skip_reason(f: dict) -> str | None:
    """Why a changed file should not be reviewed, or None to keep it."""
    path = PurePosixPath(f["filename"])
    if f["status"] == "removed":
        return "deleted (no new lines to comment on)"
    if path.name in LOCKFILES:
        return "lockfile"
    if f["changes"] > MAX_CHANGED_LINES:
        return f"{f['changes']} changed lines > {MAX_CHANGED_LINES}"
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return "binary"
    if not f.get("patch"):
        return "no patch from GitHub (binary or too large)"
    return None


def fetch_diff(state: ReviewState) -> dict:
    if state.get("files") is not None:  # evals pass the diff in directly
        print(f"fetch_diff: {len(state['files'])} pre-filled file(s), skipping the GitHub API")
        return {}

    repo, number = state["repo"], state["pr_number"]
    with github_api.session() as s:
        raw = github_api.get_all(s, f"/repos/{repo}/pulls/{number}/files", f"listing files of {repo}#{number}")

    files: list[ChangedFile] = []
    print(f"fetch_diff: {repo}#{number} changes {len(raw)} file(s)")
    for f in raw:
        reason = skip_reason(f)
        if reason:
            print(f"  skip  {f['filename']}  ({reason})")
            continue
        print(f"  keep  {f['filename']}  (+{f['additions']} -{f['deletions']})")
        files.append({"path": f["filename"], "diff": f["patch"]})
    return {"files": files}
