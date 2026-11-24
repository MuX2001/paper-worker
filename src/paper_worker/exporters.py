import re
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, StrictUndefined

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
    paper: PaperMetadata,
    analysis: PaperAnalysis,
    directory: Path,
    workspace: Path | None = None,
    registration=None,
) -> Path:
    from .athena import export_note

    return export_note(
        paper,
        analysis,
        directory,
        render_analysis(paper, analysis),
        workspace,
        registration=registration,
    )


def export_zotero(
    paper: PaperMetadata, analysis: PaperAnalysis, config: ZoteroConfig, client=None
) -> str:
    """Compatibility wrapper; analysis is intentionally not sent to Zotero."""
    from .zotero_sync import _register_web, register_paper

    if client is not None:
        return _register_web(paper, config, lambda text: None, client=client).key
    return register_paper(paper, config).key
