"""Thin GitHub REST helper shared by fetch_diff and post_comment."""

import os

import requests

API = "https://api.github.com"
TIMEOUT = 30  # seconds per request


def has_token() -> bool:
    return bool(os.getenv("GITHUB_TOKEN"))


def session() -> requests.Session:
    """A session with GitHub's recommended headers, authenticated when GITHUB_TOKEN is set.

    Public repos can be read without a token (60 requests/hour); posting needs one.
    """
    s = requests.Session()
    s.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-reviewer",
    })
    if token := os.getenv("GITHUB_TOKEN"):
        s.headers["Authorization"] = f"Bearer {token}"
    return s


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def check(resp: requests.Response, what: str) -> None:
    """Raise with GitHub's own error message instead of a bare HTTP status."""
    if resp.ok:
        return
    try:
        body = resp.json()
        detail = body.get("message", resp.text)
        if errors := body.get("errors"):
            detail += f" {errors}"
    except ValueError:
        detail = resp.text
    hint = ""
    if resp.status_code == 404:
        hint = " (wrong repo/PR number, or a private repo without a token?)"
    elif resp.status_code in (401, 403):
        hint = " (no GITHUB_TOKEN set)" if not has_token() else " (token lacks 'Pull requests: write'?)"
    raise GitHubError(f"GitHub {what} failed: {resp.status_code} {detail}{hint}", resp.status_code)


def post(s: requests.Session, path: str, payload: dict, what: str) -> dict:
    resp = s.post(f"{API}{path}", json=payload, timeout=TIMEOUT)
    check(resp, what)
    return resp.json()


def get_all(s: requests.Session, path: str, what: str) -> list[dict]:
    """GET a list endpoint and follow the Link: rel="next" pages."""
    url, params, items = f"{API}{path}", {"per_page": 100}, []
    while url:
        resp = s.get(url, params=params, timeout=TIMEOUT)
        check(resp, what)
        items.extend(resp.json())
        url = resp.links.get("next", {}).get("url")
        params = None  # the next URL already carries the query string
    return items
