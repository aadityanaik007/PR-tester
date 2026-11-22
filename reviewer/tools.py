"""Lookup tools the reviewer can call: PyPI, OSV and Wikipedia.

Each tool returns plain text, including when the lookup fails, so Claude sees the error
and carries on instead of the run crashing. Outputs are trimmed to keep prompts small.
"""

from urllib.parse import quote

import requests
from langchain_core.tools import tool

TIMEOUT = 10  # seconds per request
MAX_CHARS = 2000
HEADERS = {"User-Agent": "pr-review-agent/0.1 (automated code review)"}


def _get(url: str, **kwargs) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kwargs)


def _trim(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + " ...(trimmed)"


@tool
def pypi_package(name: str, version: str | None = None) -> str:
    """Look up a Python package on PyPI: whether it exists, its latest version and release
    date, its summary, and (if `version` is given) whether that exact version exists or was
    yanked. Use it when a PR adds, imports or pins a third-party package, to catch typos,
    made-up packages, and missing, yanked or outdated versions."""
    try:
        resp = _get(f"https://pypi.org/pypi/{quote(name)}/json")
        if resp.status_code == 404:
            return f"No package named {name!r} exists on PyPI."
        resp.raise_for_status()
        data = resp.json()
        info = data["info"]
        released = next((f["upload_time"][:10] for f in data.get("urls", [])), "unknown date")
        lines = [
            f"{info['name']}: latest version {info['version']} (released {released}).",
            f"Summary: {info.get('summary') or '(none)'}",
            f"Requires Python: {info.get('requires_python') or '(not specified)'}",
        ]
        if version:
            vresp = _get(f"https://pypi.org/pypi/{quote(name)}/{quote(version)}/json")
            if vresp.status_code == 404:
                lines.append(f"Version {version} does not exist on PyPI.")
            else:
                vresp.raise_for_status()
                vinfo = vresp.json()["info"]
                if vinfo.get("yanked"):
                    lines.append(f"Version {version} exists but was YANKED: {vinfo.get('yanked_reason') or 'no reason given'}.")
                else:
                    lines.append(f"Version {version} exists and is not yanked.")
        return _trim("\n".join(lines))
    except requests.RequestException as e:
        return f"PyPI lookup for {name!r} failed: {e}"


@tool
def osv_vulnerabilities(package: str, version: str) -> str:
    """Known security vulnerabilities (CVE/GHSA) affecting one version of a PyPI package,
    from the OSV database (osv.dev), with the versions that fix them. Use it when a PR adds
    or changes a pinned dependency version."""
    try:
        resp = requests.post(
            "https://api.osv.dev/v1/query",
            json={"package": {"name": package, "ecosystem": "PyPI"}, "version": version},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        vulns = resp.json().get("vulns", [])
    except requests.RequestException as e:
        return f"OSV lookup for {package} {version} failed: {e}"
    if not vulns:
        return f"OSV lists no known vulnerabilities for {package} {version}."

    lines = [f"OSV lists {len(vulns)} known vulnerabilit{'y' if len(vulns) == 1 else 'ies'} for {package} {version}:"]
    for v in vulns[:10]:
        cves = [a for a in v.get("aliases", []) if a.startswith("CVE-")]
        fixed = sorted({
            event["fixed"]
            for affected in v.get("affected", [])
            for rng in affected.get("ranges", [])
            for event in rng.get("events", [])
            if "fixed" in event
        })
        ident = v["id"] + (f" ({', '.join(cves)})" if cves else "")
        lines.append(f"- {ident}: {v.get('summary') or 'no summary'}. Fixed in: {', '.join(fixed) or 'no fix listed'}.")
    if len(vulns) > 10:
        lines.append(f"... and {len(vulns) - 10} more.")
    return _trim("\n".join(lines))


@tool
def wikipedia_summary(topic: str) -> str:
    """Short Wikipedia summary of a named concept, algorithm, standard or formula, for
    example 'Luhn algorithm', 'ISO 4217' or 'Haversine formula'. Use it to check that code
    claiming to implement a named concept actually matches its definition."""
    try:
        search = _get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "opensearch", "search": topic, "limit": 1, "namespace": 0, "format": "json"},
        )
        search.raise_for_status()
        titles = search.json()[1]
        if not titles:
            return f"No Wikipedia article found for {topic!r}."
        title = titles[0]
        page = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}")
        page.raise_for_status()
        extract = page.json().get("extract") or "(no summary available)"
        return _trim(f"Wikipedia, '{title}': {extract}")
    except requests.RequestException as e:
        return f"Wikipedia lookup for {topic!r} failed: {e}"


TOOLS = [pypi_package, osv_vulnerabilities, wikipedia_summary]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}
