"""GitHub integration: fetch a PR's diff and post the review back.

Used by ``diffsentry review --pr N --repo owner/name`` locally and by
the composite GitHub Action in CI. Auth is the standard GITHUB_TOKEN
environment variable — in Actions it is provided automatically.
"""

from __future__ import annotations

import os

import httpx

API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def fetch_pr_diff(repo: str, pr_number: int) -> str:
    headers = _headers() | {"Accept": "application/vnd.github.diff"}
    resp = httpx.get(f"{API}/repos/{repo}/pulls/{pr_number}",
                     headers=headers, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def post_pr_comment(repo: str, pr_number: int, body: str) -> str:
    resp = httpx.post(f"{API}/repos/{repo}/issues/{pr_number}/comments",
                      headers=_headers(), json={"body": body}, timeout=60)
    resp.raise_for_status()
    return resp.json()["html_url"]
