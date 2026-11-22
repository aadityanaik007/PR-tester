"""Run settings: which PR to review, and whether to post or just print."""

import argparse
import os


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def dry_run() -> bool:
    """DRY_RUN=true prints the review instead of posting it to GitHub."""
    return _truthy(os.getenv("DRY_RUN"))


def check_can_post() -> None:
    """Fail at startup, before any LLM spend, if the run would end unable to post."""
    if not dry_run() and not os.getenv("GITHUB_TOKEN"):
        raise SystemExit("GITHUB_TOKEN is needed to post the review. Set it, or set DRY_RUN=true to print instead.")


def get_target(argv: list[str] | None = None) -> tuple[str, int]:
    """Return (repo, pr_number).

    Env vars come first (GITHUB_REPOSITORY, PR_NUMBER) so GitHub Actions can drive
    the same entry point; --repo / --pr are the fallback for local runs.
    """
    parser = argparse.ArgumentParser(description="Review a GitHub pull request.")
    parser.add_argument("--repo", help="owner/name, used when GITHUB_REPOSITORY is unset")
    parser.add_argument("--pr", type=int, help="PR number, used when PR_NUMBER is unset")
    args = parser.parse_args(argv)

    repo = os.getenv("GITHUB_REPOSITORY") or args.repo
    pr = os.getenv("PR_NUMBER") or args.pr
    if not repo or not pr:
        parser.error("set GITHUB_REPOSITORY and PR_NUMBER (env or .env), or pass --repo and --pr")
    try:
        return repo, int(pr)
    except ValueError:
        parser.error(f"PR number must be an integer, got {pr!r}")
