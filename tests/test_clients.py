import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from paper_worker.arxiv_client import fetch_paper
from paper_worker.codex_runner import run_codex
from paper_worker.config import Config, load_config, save_config
from paper_worker.github_audit import fetch_repo_context


def test_arxiv_http(tmp_path):
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v1</id><title>Title\n text</title><author><name>Author</name></author><summary>Abstract</summary><published>2017-06-12</published></entry></feed>"""

    def handler(request):
        if "api/query" in str(request.url):
            assert request.url.params["id_list"] == "1706.03762"
            return httpx.Response(200, text=atom)
        return httpx.Response(200, content=b"%PDF-1.4 fixture")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        paper, pdf = fetch_paper("1706.03762", tmp_path, client)
    assert paper.title == "Title text"
    assert pdf.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("empty", [False, True])
def test_github_http(tmp_path, empty):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer token"
        path = request.url.path
        if path.endswith("/readme"):
            return httpx.Response(200, json={"content": base64.b64encode(b"# Repo").decode()})
        if path.endswith("/issues"):
            return httpx.Response(
                200, json=[{"title": "PR", "pull_request": {}}, {"title": "Cannot reproduce"}]
            )
        if "/git/trees/" in path:
            if empty:
                return httpx.Response(409)
            return httpx.Response(200, json={"tree": [{"path": "model.py"}], "truncated": False})
        return httpx.Response(200, json={"default_branch": "main"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = fetch_repo_context(["https://github.com/o/r"], tmp_path, client, "token")
    repo = json.loads(path.read_text())["candidate_repositories"][0]
    assert repo["open_issues"] == ["Cannot reproduce"]
    assert repo["tree"] == ([] if empty else ["model.py"])


def test_codex_retry(tmp_path, analysis):
    replies = [
        SimpleNamespace(returncode=0, stdout="invalid output", stderr=""),
        SimpleNamespace(returncode=0, stdout=analysis.model_dump_json(), stderr=""),
    ]
    with patch("paper_worker.codex_runner.subprocess.run", side_effect=replies) as run:
        result = run_codex(
            Config(codex_command="codex exec"), tmp_path, tmp_path / "paper.pdf", None
        )
    assert result == analysis
    assert run.call_count == 2
    assert "Previous output failed validation" in run.call_args.kwargs["input"]
    assert run.call_args.kwargs.get("shell", False) is False


def test_codex_invalid_twice(tmp_path):
    reply = SimpleNamespace(returncode=0, stdout="{}", stderr="")
    with patch("paper_worker.codex_runner.subprocess.run", return_value=reply) as run:
        with pytest.raises(ValueError):
            run_codex(Config(codex_command="codex exec"), tmp_path, tmp_path / "paper.pdf", None)
    assert run.call_count == 2


def test_config_roundtrip_and_secret_errors(tmp_path):
    config = Config(github_token="token", obsidian_vault_dir="notes")
    path = tmp_path / "config.yaml"
    save_config(config, path)
    restored = load_config(path)
    assert restored.github_token.get_secret_value() == "token"
    assert restored.obsidian_vault_dir == tmp_path / "notes"
    with pytest.raises(ValueError) as caught:
        Config(zotero={"mode": "web", "api_key": "super-secret"})
    assert "super-secret" not in str(caught.value)


def test_github_rate_limit(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1795515757"}
            )
        )
    ) as client:
        with pytest.raises(RuntimeError, match="Configure github_token"):
            fetch_repo_context(["https://github.com/o/r"], tmp_path, client)
