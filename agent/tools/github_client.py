"""
GitHub REST API client — read/write files, create PRs.

Lightweight implementation using requests (no PyGithub dependency).
Environment variables are loaded lazily so the agent can run without
GitHub access for health-check tasks.
"""

from __future__ import annotations

import base64
import os

import requests

from agent.config import get_logger

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"


# ── Helpers ──────────────────────────────────────────────────────


def _get_headers() -> dict:
    """Build GitHub API headers from env var."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN is required for GitHub operations")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_repo() -> str:
    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise ValueError("GITHUB_REPO is required (format: owner/repo)")
    return repo


def _get_default_branch() -> str:
    return os.environ.get("GITHUB_DEFAULT_BRANCH", "main")


# ── Public API ───────────────────────────────────────────────────


def get_file(path: str, ref: str = "") -> dict:
    """
    Get a file from the GitHub repository.

    Args:
        path: File path in the repo (e.g. "agent/config.py").
        ref:  Branch or commit ref.  Default: repo default branch.

    Returns:
        Dict with keys: path, content (decoded text), sha, size.
    """
    repo = _get_repo()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    params = {}
    if ref:
        params["ref"] = ref

    resp = requests.get(url, headers=_get_headers(), params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    content = base64.b64decode(data["content"]).decode("utf-8")
    logger.info("get_file: %s (%d bytes)", path, data.get("size", 0))
    return {
        "path": data["path"],
        "content": content,
        "sha": data["sha"],
        "size": data.get("size", 0),
    }


def update_file(
    path: str,
    content: str,
    message: str,
    branch: str = "",
) -> dict:
    """
    Create or update a file in the GitHub repository.

    Args:
        path:    File path in the repo.
        content: New file content (full text, not a patch).
        message: Git commit message.
        branch:  Target branch.  Default: repo default branch.

    Returns:
        Dict with keys: commit_sha, path, branch.
    """
    repo = _get_repo()
    branch = branch or _get_default_branch()
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"

    # Get current SHA if file exists (required for update)
    sha = None
    try:
        existing = get_file(path, ref=branch)
        sha = existing["sha"]
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code != 404:
            raise

    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=_get_headers(), json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    commit_sha = data["commit"]["sha"]
    logger.info("update_file: %s on %s → %s", path, branch, commit_sha[:8])
    return {
        "commit_sha": commit_sha,
        "path": path,
        "branch": branch,
    }


def create_pull_request(
    title: str,
    body: str,
    head: str,
    base: str = "",
) -> dict:
    """
    Create a pull request on GitHub.

    Args:
        title: PR title.
        body:  PR description (supports markdown).
        head:  Source branch name.
        base:  Target branch.  Default: repo default branch.

    Returns:
        Dict with keys: pr_number, url, html_url, state.
    """
    repo = _get_repo()
    base = base or _get_default_branch()
    url = f"{GITHUB_API}/repos/{repo}/pulls"

    resp = requests.post(
        url,
        headers=_get_headers(),
        json={
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    logger.info("create_pull_request: #%d %s", data["number"], title)
    return {
        "pr_number": data["number"],
        "url": data["url"],
        "html_url": data["html_url"],
        "state": data["state"],
    }
