import json
from unittest.mock import patch

import pytest

from paper_worker.arxiv_client import normalize_arxiv_id
from paper_worker.codex_runner import extract_analysis
from paper_worker.config import Config
from paper_worker.github_audit import extract_github_urls
from paper_worker.pipeline import run_pipeline


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1706.03762", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762v2.pdf", "1706.03762v2"),
        ("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001"),
    ],
)
def test_arxiv(value, expected):
    assert normalize_arxiv_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.test/1706.03762",
        "../../secret",
        "123",
        "https://arxiv.org.evil.test/abs/1706.03762",
    ],
)
def test_invalid_arxiv(value):
    with pytest.raises(ValueError):
        normalize_arxiv_id(value)


def test_github_extraction():
    assert extract_github_urls(
        "(https://github.com/owner/repo.git). https://github.com/owner/repo/tree/main https://evilgithub.com/o/r"
    ) == ["https://github.com/owner/repo"]


def test_github_pdf_line_wrap():
    assert extract_github_urls("https://github.com/\ntensorflow/tensor2tensor.") == [
        "https://github.com/tensorflow/tensor2tensor"
    ]


def test_json_extraction(analysis):
    assert (
        extract_analysis("progress {}\n```json\n" + analysis.model_dump_json() + "\n```")
        == analysis
    )
    bad = analysis.model_dump()
    bad["hype_flag"] = True
    with pytest.raises(ValueError, match="hype_reason"):
        extract_analysis(json.dumps(bad))


def test_core_pipeline(tmp_path, paper, analysis):
    with (
        patch("paper_worker.pipeline.fetch_paper", return_value=(paper, tmp_path / "paper.pdf")),
        patch("paper_worker.pipeline.extract_text", return_value=("full text", "link text")),
        patch("paper_worker.pipeline.fetch_repo_context", return_value=None),
        patch("paper_worker.pipeline.run_codex", return_value=analysis),
    ):
        result = run_pipeline(
            paper.arxiv_id, Config(cache_dir=tmp_path), obsidian=False, zotero=False
        )
    assert result.analysis == analysis
    assert (result.workspace / "analysis.json").exists()
    assert (result.workspace / "paper.txt").read_text() == "full text"
