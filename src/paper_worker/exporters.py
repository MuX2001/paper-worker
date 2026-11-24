from pathlib import Path

from .config import ZoteroConfig
from .schemas import PaperAnalysis, PaperMetadata


def render_analysis(paper: PaperMetadata, analysis: PaperAnalysis) -> str:
    if not analysis.note_body.strip():
        raise ValueError(
            "Full Paper Analysis is missing. A short summary cannot be exported as an Athena paper note."
        )
    return analysis.note_body


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
