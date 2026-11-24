import re
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, StrictUndefined

from .arxiv_client import base_id, normalize_arxiv_id
from .config import ZoteroConfig
from .schemas import PaperAnalysis, PaperMetadata


def render_analysis(paper: PaperMetadata, analysis: PaperAnalysis) -> str:
    if analysis.note_body:
        return analysis.note_body
    if re.search(r"[\u4e00-\u9fff]", analysis.tldr):
        raise ValueError("Legacy Chinese summary must be regenerated in English for Athena")
    environment = Environment(
        undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True
    )
    environment.filters["table_cell"] = lambda value: value.replace("|", "\\|").replace(
        "\n", "<br>"
    )
    template = environment.from_string(
        files("paper_worker")
        .joinpath("templates/analysis_summary.md.j2")
        .read_text(encoding="utf-8")
    )
    return template.render(paper=paper, analysis=analysis)


def export_obsidian(
    paper: PaperMetadata, analysis: PaperAnalysis, directory: Path, workspace: Path | None = None
) -> Path:
    from .athena import export_note

    return export_note(paper, analysis, directory, render_analysis(paper, analysis), workspace)


def export_zotero(
    paper: PaperMetadata, analysis: PaperAnalysis, config: ZoteroConfig, client=None
) -> str:
    if not config.enabled:
        raise ValueError("Zotero Library ID and API Key are required")
    if client is None:
        from pyzotero import zotero

        client = zotero.Zotero(
            config.library_id, config.library_type, config.api_key.get_secret_value()
        )
    canonical = base_id(paper.arxiv_id)
    # Fulltext search includes Extra; paginate before exact matching to avoid false duplicates.
    items = client.everything(client.items(q=canonical, qmode="everything"))
    for item in items:
        data = item.get("data", {})
        values = [data.get("url", ""), data.get("archiveID", "")]
        values.extend(re.findall(r"(?im)^arxiv:\s*(\S+)", data.get("extra", "")))
        for value in values:
            try:
                if base_id(normalize_arxiv_id(value)) == canonical:
                    return item["key"]
            except ValueError:
                continue
    template = client.item_template("preprint")
    template.update(
        {
            "title": paper.title,
            "abstractNote": paper.abstract,
            "url": paper.url,
            "date": paper.published[:10],
            "repository": "arXiv",
            "archiveID": canonical,
            "extra": f"arXiv: {canonical}",
            "creators": [{"creatorType": "author", "name": name} for name in paper.authors],
            "tags": [
                {"tag": tag}
                for tag in analysis.tags
                + [f"code:{analysis.code_status}"]
                + (["hype-warning"] if analysis.hype_flag else [])
            ],
        }
    )
    if config.collection_key:
        template["collections"] = [config.collection_key]
    response = client.create_items([template])
    if response.get("failed"):
        raise RuntimeError(f"Zotero rejected item: {response['failed']}")
    key = response.get("success", {}).get("0")
    if not key:
        key = response.get("successful", {}).get("0", {}).get("key")
    if not key:
        raise RuntimeError("Zotero did not return a created item key")
    return key
