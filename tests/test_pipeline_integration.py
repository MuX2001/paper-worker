import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from paper_worker.config import Config
from paper_worker.pipeline import run_pipeline


def paper_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 40 740 Td (Code: https://github.com/example/research) Tj ET")
    page[NameObject("/Contents")] = content
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_full_pipeline_passes_repository_evidence_and_exports(tmp_path, athena_vault, analysis):
    analysis.repo_url = "https://github.com/example/research"
    analysis.code_status = "partial"
    from paper_worker.schemas import CodeAuditItem

    analysis.code_audit = [
        CodeAuditItem(paper_module="Attention", file_path="model.py", status="unclear")
    ]
    pdf = paper_pdf()
    requests = []

    def http_handler(request):
        requests.append(request)
        if request.url.host == "export.arxiv.org":
            return httpx.Response(
                200,
                text="""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/1706.03762</id><title>Test Paper</title><author><name>Author</name></author><summary>Research</summary><published>2017-06-12</published></entry></feed>""",
            )
        if request.url.host == "arxiv.org":
            return httpx.Response(200, content=pdf)
        if request.url.path.endswith("/readme"):
            return httpx.Response(
                200, json={"content": base64.b64encode(b"# Research implementation").decode()}
            )
        if request.url.path.endswith("/issues"):
            return httpx.Response(200, json=[{"title": "Reproduction question"}])
        if "/git/trees/" in request.url.path:
            return httpx.Response(200, json={"tree": [{"path": "model.py"}], "truncated": False})
        return httpx.Response(200, json={"default_branch": "main"})

    def codex_process(args, **kwargs):
        workspace = kwargs["cwd"]
        context = workspace / "repo_context.txt"
        assert str(context) in kwargs["input"]
        repo = json.loads(context.read_text(encoding="utf-8"))["candidate_repositories"][0]
        assert repo["tree"] == ["model.py"]
        assert repo["open_issues"] == ["Reproduction question"]
        assert "github.com/example/research" in (workspace / "paper.txt").read_text(
            encoding="utf-8"
        )
        return SimpleNamespace(returncode=0, stdout=analysis.model_dump_json(), stderr="")

    client = httpx.Client(transport=httpx.MockTransport(http_handler))
    config = Config(
        cache_dir=tmp_path / "cache",
        obsidian_vault_dir=athena_vault,
        codex_command="codex exec",
    )
    import subprocess

    real_run = subprocess.run

    def process_dispatch(args, **kwargs):
        if "--output-schema" in args:
            return codex_process(args, **kwargs)
        return real_run(args, **kwargs)

    with (
        patch("paper_worker.pipeline.httpx.Client", return_value=client),
        patch("paper_worker.codex_runner.subprocess.run", side_effect=process_dispatch),
    ):
        result = run_pipeline("1706.03762", config, zotero=False)
    note = result.note_path.read_text(encoding="utf-8")
    assert "| Attention | model.py | unclear |" in note
    assert "Code status: partial" in note
    assert len(requests) == 6
    assert (result.workspace / "analysis.json").exists()
