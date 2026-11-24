import shutil
from pathlib import Path

import pytest

from paper_worker.schemas import PaperAnalysis, PaperMetadata


@pytest.fixture
def analysis():
    return PaperAnalysis(
        tldr="Sparse attention reduces compute",
        problem="Dense attention is expensive",
        method_details=["Sparse attention"],
        experiments={"datasets": ["Example"], "key_results": "2x speedup", "red_flags": "None"},
        tags=["sparse-attention"],
        repo_url=None,
        code_status="no_repo",
        code_audit=[],
        missing_assets=[],
        hype_flag=False,
    )


@pytest.fixture
def paper():
    return PaperMetadata(
        arxiv_id="1706.03762v1",
        title="Attention: Is All You Need",
        authors=["A. Author"],
        abstract="Abstract",
        published="2017-06-12",
        url="https://arxiv.org/abs/1706.03762v1",
        pdf_url="https://arxiv.org/pdf/1706.03762v1",
    )


@pytest.fixture
def athena_vault(tmp_path):
    vault = tmp_path / "Athena"
    shutil.copytree(Path(__file__).parent / "fixtures/athena", vault)
    return vault
