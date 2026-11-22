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


def check(resp: requests.Response, what: str) -> None:
    """Raise with GitHub's own error message instead of a bare HTTP status."""
    if resp.ok:
        return
    try:
        detail = resp.json().get("message", resp.text)
    except ValueError:
        detail = resp.text
    hint = ""
    if resp.status_code == 404:
        hint = " (wrong repo/PR number, or a private repo without a token?)"
    elif resp.status_code in (401, 403) and not has_token():
        hint = " (no GITHUB_TOKEN set)"
    raise RuntimeError(f"GitHub {what} failed: {resp.status_code} {detail}{hint}")


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
