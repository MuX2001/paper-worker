import base64
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

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
        if repo.status_code in {403, 429} and repo.headers.get("x-ratelimit-remaining") == "0":
            contexts.append(public_archive_context(url, client))
            continue
        check_response(repo)
        info = repo.json()
        context = {
            "url": url,
            "description": info.get("description"),
            "default_branch": info["default_branch"],
        }
        revision = client.get(
            f"{endpoint}/commits/{quote(info['default_branch'], safe='')}", headers=headers
        )
        if revision.status_code != 409:
            check_response(revision)
        commit = revision.json().get("sha") if revision.is_success else None
        context["commit"] = commit
        context["archived"] = info.get("archived")
        context["license"] = (info.get("license") or {}).get("spdx_id")
        tree = client.get(
            f"{endpoint}/git/trees/{commit or info['default_branch']}",
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
        readme = client.get(
            f"{endpoint}/readme", headers=headers, params={"ref": commit} if commit else {}
        )
        if readme.status_code == 404:
            context["readme"] = "README unavailable"
        else:
            check_response(readme)
            context["readme"] = base64.b64decode(readme.json().get("content", "")).decode(
                "utf-8", errors="replace"
            )[:60000]
        snippets = []
        if commit:
            blobs = [
                item
                for item in tree.json().get("tree", [])
                if item.get("type") == "blob" and 0 < item.get("size", 0) < 250000
            ]
            selected = set()
            for category, pattern in [
                ("model", r"(?i)(?:model|transformer|network).*\.py$"),
                ("training", r"(?i)(?:config|train|hparam).*\.(?:yaml|yml|py|json)$"),
                ("data", r"(?i)(?:dataset|preprocess|data_generator).*\.py$"),
                ("evaluation", r"(?i)(?:eval|score|metric).*\.py$"),
                ("environment", r"(?i)(?:requirements\.txt|setup\.py|pyproject\.toml)$"),
            ]:
                choices = [
                    b
                    for b in blobs
                    if b["path"] not in selected
                    and re.search(pattern, b["path"])
                    and not re.search(r"(?i)(?:test|vendor|third_party)", b["path"])
                ]
                if not choices:
                    continue
                blob = min(choices, key=lambda b: (b["path"].count("/"), len(b["path"]), b["path"]))
                selected.add(blob["path"])
                source = client.get(f"{endpoint}/git/blobs/{blob['sha']}", headers=headers)
                if not source.is_success:
                    snippets.append({"path": blob["path"], "http_status": source.status_code})
                    continue
                content = base64.b64decode(source.json()["content"]).decode(
                    "utf-8", errors="replace"
                )
                snippets.append(
                    {
                        "category": category,
                        "path": blob["path"],
                        "url": f"{url}/blob/{commit}/{quote(blob['path'])}",
                        "text": content[:20000],
                        "truncated": len(content) > 20000,
                    }
                )
        context["sources"] = snippets
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
                "evidence_limits": "Only supplied source excerpts establish code contents. A recent commit need not match the paper revision. No code was executed.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def public_archive_context(url: str, client: httpx.Client) -> dict:
    """Read a bounded public source snapshot in memory during REST rate limiting."""
    result = {"url": url, "open_issues_status": "unavailable: REST rate limit", "sources": []}
    slug = url.removeprefix("https://github.com/")
    try:
        with client.stream("GET", f"https://codeload.github.com/{slug}/zip/HEAD") as response:
            response.raise_for_status()
            buffer = io.BytesIO()
            for chunk in response.iter_bytes(65536):
                if buffer.tell() + len(chunk) > 16 * 1024 * 1024:
                    result["archive_status"] = "exceeds 16 MiB download limit"
                    return result
                buffer.write(chunk)
        with zipfile.ZipFile(buffer) as archive:
            commit = archive.comment.decode("ascii", errors="replace")
            if not re.fullmatch("[a-f0-9]{40}", commit):
                result["archive_status"] = "archive did not identify its commit"
                return result
            result["commit"] = commit
            files = {i.filename.partition("/")[2]: i for i in archive.infolist() if not i.is_dir()}
            result["tree"] = list(files)
            selected = set()
            patterns = [
                r"^readme\.md$",
                r"(?i)(?:transformer|model|network)\.py$",
                r"(?i)(?:config|hparam|train)[^/]*\.(?:py|ya?ml)$",
                r"(?i)(?:preprocess|dataset|translate_ende)[^/]*\.py$",
                r"(?i)(?:bleu|scorer|evaluate)[^/]*\.py$",
                r"(?i)(?:setup\.py|pyproject\.toml)$",
            ]
            for pattern in patterns:
                choices = [
                    p
                    for p, i in files.items()
                    if p not in selected
                    and i.file_size < 250000
                    and re.search(pattern, p, re.I)
                    and "test" not in p.lower()
                ]
                if choices:
                    path = min(choices, key=lambda p: (p.count("/"), len(p), p))
                    selected.add(path)
                    content = archive.read(files[path]).decode("utf-8", errors="replace")
                    result["sources"].append(
                        {
                            "path": path,
                            "text": content[:20000],
                            "truncated": len(content) > 20000,
                            "url": f"{url}/blob/{commit}/{quote(path)}",
                        }
                    )
    except (httpx.HTTPError, zipfile.BadZipFile) as exc:
        result["archive_status"] = str(exc)
    return result
