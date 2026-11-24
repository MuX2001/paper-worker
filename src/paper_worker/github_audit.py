import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx


def check_response(response: httpx.Response) -> None:
    if response.status_code in {403, 429} and response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset", "")
        when = ""
        if reset.isdigit():
            when = " Reset: " + datetime.fromtimestamp(int(reset), timezone.utc).isoformat()
        raise RuntimeError(
            "GitHub API rate limit exhausted. Configure github_token in Settings or retry after reset."
            + when
        )
    response.raise_for_status()


def extract_github_urls(text: str) -> list[str]:
    # PDF layout often wraps links immediately after a slash.
    text = re.sub(r"(github\.com/)\s+", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"(github\.com/[\w-]+/)\s+", r"\1", text, flags=re.IGNORECASE)
    matches = re.findall(
        r"(?<![\w.])(?:https?://)?(?:www\.)?github\.com/([\w-]+)/([\w.\-]+)", text, re.I
    )
    urls = []
    for owner, repo in matches:
        repo = repo.rstrip(".-").removesuffix(".git")
        if owner.lower() in {"features", "topics", "orgs", "settings", "search"} or not repo:
            continue
        url = f"https://github.com/{owner}/{repo}"
        if url.lower() not in [u.lower() for u in urls]:
            urls.append(url)
    return urls


def fetch_repo_context(
    urls: list[str], workspace: Path, client: httpx.Client, token: str = ""
) -> Path | None:
    if not urls:
        return None
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    contexts = []
    for url in urls[:5]:
        slug = url.removeprefix("https://github.com/")
        endpoint = f"https://api.github.com/repos/{slug}"
        repo = client.get(endpoint, headers=headers)
        check_response(repo)
        info = repo.json()
        context = {
            "url": url,
            "description": info.get("description"),
            "default_branch": info["default_branch"],
        }
        tree = client.get(
            f"{endpoint}/git/trees/{info['default_branch']}",
            params={"recursive": "1"},
            headers=headers,
        )
        if tree.status_code == 409:
            context["tree"] = []
            context["empty_repository"] = True
        else:
            check_response(tree)
            context["tree"] = [entry["path"] for entry in tree.json().get("tree", [])]
            context["tree_truncated"] = tree.json().get("truncated", False)
        readme = client.get(f"{endpoint}/readme", headers=headers)
        if readme.status_code == 404:
            context["readme"] = "README unavailable"
        else:
            check_response(readme)
            context["readme"] = base64.b64decode(readme.json().get("content", "")).decode(
                "utf-8", errors="replace"
            )[:60000]
        issues = client.get(
            f"{endpoint}/issues",
            params={"state": "open", "sort": "created", "direction": "desc", "per_page": 100},
            headers=headers,
        )
        check_response(issues)
        context["open_issues"] = [i["title"] for i in issues.json() if "pull_request" not in i][:10]
        contexts.append(context)
    path = workspace / "repo_context.txt"
    path.write_text(
        json.dumps(
            {
                "candidate_repositories": contexts,
                "omitted_candidates": urls[5:],
                "evidence_limits": "Tree, README and issue titles only; source bodies were not inspected.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
