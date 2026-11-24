import uuid
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from .arxiv_client import download_pdf, extract_text, fetch_metadata, normalize_arxiv_id
from .codex_runner import run_codex
from .config import Config
from .github_audit import extract_github_urls, fetch_repo_context
from .schemas import PaperAnalysis, PaperMetadata
from .zotero_sync import register_paper


@dataclass
class PipelineResult:
    metadata: PaperMetadata
    analysis: PaperAnalysis
    workspace: Path
    note_path: Path | None = None
    zotero_key: str | None = None
    zotero_uri: str | None = None


def run_pipeline(
    value: str, config: Config, *, obsidian: bool = True, zotero: bool = True, log=print
) -> PipelineResult:
    if obsidian:
        from .athena import vault_root

        vault_root(config.obsidian_vault_dir)
    arxiv_id = normalize_arxiv_id(value)
    workspace = (
        config.cache_dir.expanduser() / arxiv_id.replace("/", "_") / uuid.uuid4().hex[:12]
    ).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    registration = None
    with httpx.Client(
        timeout=90,
        follow_redirects=True,
        headers={"User-Agent": "paper-worker/0.1 (local research archiver)"},
    ) as client:
        log(f"1/6 Fetching arXiv {arxiv_id}")
        metadata = fetch_metadata(arxiv_id, client)
        if zotero:
            log("2/6 Registering bibliography in Zotero")
            registration = register_paper(metadata, config.zotero, log=log)
            (workspace / "zotero.json").write_text(
                json.dumps(asdict(registration), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"Zotero: {registration.uri}")
        pdf = download_pdf(metadata, workspace, client)
        full_text, link_text = extract_text(pdf)
        (workspace / "paper.txt").write_text(full_text, encoding="utf-8")
        (workspace / "metadata.json").write_text(
            metadata.model_dump_json(indent=2), encoding="utf-8"
        )
        log("3/6 Collecting GitHub evidence")
        candidates = extract_github_urls(metadata.abstract + "\n" + link_text)
        if not candidates:
            candidates = extract_github_urls(full_text)
        repo = fetch_repo_context(
            candidates,
            workspace,
            client,
            config.github_token.get_secret_value(),
        )
    log("4/6 Analyzing paper with Codex")
    analysis = run_codex(config, workspace, pdf, repo, log)
    (workspace / "analysis.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    result = PipelineResult(metadata, analysis, workspace)
    if registration:
        result.zotero_key = registration.key
        result.zotero_uri = registration.uri
    if obsidian:
        from .exporters import export_obsidian

        log("5/6 Writing linked Obsidian note")
        result.note_path = export_obsidian(
            metadata, analysis, config.obsidian_vault_dir, workspace, registration=registration
        )
        log(f"Obsidian: {result.note_path}")
    log(f"Finished: code_status={analysis.code_status}, hype_flag={analysis.hype_flag}")
    return result
