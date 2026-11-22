"""Shared state passed between every node in the review graph."""

from typing import TypedDict


class ChangedFile(TypedDict):
    path: str
    diff: str


class ReviewComment(TypedDict):
    path: str
    line: int
    severity: str  # "bug", "warning" or "nit"
    issue: str
    suggestion: str


class ReviewState(TypedDict, total=False):
    repo: str                          # e.g. "yourname/pr-review-test"
    pr_number: int
    files: list[ChangedFile]           # changed files and their diffs
    context: dict[str, list[str]]      # retrieved code snippets, keyed by file path
    draft_comments: list[ReviewComment]
    final_comments: list[ReviewComment]
    needs_retry: bool                  # set by the verifier
    attempts: int                      # how many times the reviewer has run
    index_dir: str                     # evals only: folder for retrieve to index instead of project/