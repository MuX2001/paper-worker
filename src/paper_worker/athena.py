"""Athena adapter: shared template, identity checks and protected helper updates."""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .arxiv_client import base_id
from .schemas import PaperAnalysis, PaperMetadata

BEGIN = "<!-- paper-analysis:begin -->"
END = "<!-- paper-analysis:end -->"


def vault_root(directory: Path) -> Path:
    directory = directory.expanduser().resolve()
    for root in (directory, *directory.parents):
        if (root / "_template/_template_paper.md").is_file():
            return root
    raise ValueError("Configure an Athena vault containing _template/_template_paper.md")


def frontmatter(raw: bytes) -> dict:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", raw.decode("utf-8-sig"), re.S)
    if not match:
        return {}
    data = yaml.safe_load(match[1])
    if not isinstance(data, dict):
        raise ValueError("Paper frontmatter must be a mapping")
    return data


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", str(value)).casefold() if c.isalnum())


def normalized_doi(value: str) -> str:
    return re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", str(value).strip(), flags=re.I
    ).casefold()


def find_existing(root: Path, paper: PaperMetadata) -> Path | None:
    candidates = []
    for path in root.rglob("*.md"):
        if any(
            part.startswith(".") or part in {"_template", "__resource"}
            for part in path.relative_to(root).parts
        ):
            continue
        raw = path.read_bytes()
        try:
            meta = frontmatter(raw)
        except (ValueError, yaml.YAMLError) as exc:
            content = raw.decode("utf-8-sig", errors="replace")
            if base_id(paper.arxiv_id) in content or normalized(paper.title) in normalized(content):
                raise ValueError(
                    f"Potential matching note has invalid metadata; review {path}"
                ) from exc
            continue
        matched = False
        if meta.get("arxiv_id"):
            try:
                matched = base_id(str(meta["arxiv_id"])) == base_id(paper.arxiv_id)
            except ValueError:
                pass
        if paper.doi and meta.get("doi"):
            doi_match = normalized_doi(meta["doi"]) == normalized_doi(paper.doi)
            if matched and not doi_match:
                raise ValueError(f"Conflicting DOI/arXiv identity: {path}")
            if doi_match and meta.get("arxiv_id") and not matched:
                raise ValueError(f"Conflicting DOI/arXiv identity: {path}")
            matched = matched or doi_match
        title_match = bool(meta.get("title")) and normalized(meta["title"]) == normalized(
            paper.title
        )
        if title_match and not matched:
            authors = meta.get("authors", [])
            if isinstance(authors, str):
                authors = [authors]
            if str(meta.get("year", "")) != paper.published[:4] or not (
                {normalized(a) for a in authors} & {normalized(a) for a in paper.authors}
            ):
                raise ValueError(f"Title match needs author/year identity review: {path}")
            if meta.get("arxiv_id") or (paper.doi and meta.get("doi")):
                raise ValueError(f"Title matches but stable identifiers conflict: {path}")
            matched = True
        if matched:
            candidates.append(path)
    if len(candidates) > 1:
        raise ValueError(
            "Multiple notes match this paper; resolve identity before writing: "
            + ", ".join(map(str, candidates))
        )
    return candidates[0] if candidates else None


def _helper(root: Path, script: str, args: list[str]) -> None:
    helper = root / "__resource/paper-workflow" / script
    if not helper.is_file():
        raise ValueError(f"Required Athena workflow helper is missing: {helper}")
    result = subprocess.run(
        [sys.executable, "-B", str(helper), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Athena {script}: {result.stdout.strip()} {result.stderr.strip()}")


def export_note(
    paper: PaperMetadata,
    analysis: PaperAnalysis,
    directory: Path,
    body: str,
    workspace: Path | None = None,
) -> Path:
    root = vault_root(directory)
    existing = find_existing(root, paper)
    original = (
        existing.read_bytes() if existing else (root / "_template/_template_paper.md").read_bytes()
    )
    meta = frontmatter(original)
    text = original.decode("utf-8-sig")
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError(
            f"Legacy note needs a separate reviewed migration; no overwrite: {existing}"
        )
    if existing and meta.get("analysis_status") == "complete":
        raise ValueError(
            "Existing complete analysis requires reviewed replacement; automated draft will not overwrite it"
        )
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="paper-worker-review-"))
    workspace = workspace.resolve()
    if workspace == root or root in workspace.parents:
        raise ValueError("Snapshots and candidates must be stored outside the vault")
    workspace.mkdir(parents=True, exist_ok=True)
    snapshot = workspace / "note-before.md"
    snapshot.write_bytes(original)
    candidate = workspace / "note-candidate.md"
    candidate.write_bytes(original)
    if not existing and analysis.paper_type == "survey":
        candidate.write_bytes(
            re.sub(rb"(?m)^resource_type: paper\r?$", b"resource_type: survey", original)
        )
    fields = {
        "title": paper.title,
        "authors": paper.authors,
        "year": int(paper.published[:4]),
        "arxiv_id": base_id(paper.arxiv_id),
        "url": paper.url,
        "analysis_status": "incomplete",
        "analysis_source": paper.pdf_url,
        "analysis_version": re.search(r"v\d+$", paper.arxiv_id)[0]
        if re.search(r"v\d+$", paper.arxiv_id)
        else "unresolved arXiv revision",
        "analysis_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "analysis_spec": "1.1",
    }
    if paper.doi:
        fields["doi"] = paper.doi
    body_path = workspace / "reviewed-analysis.md"
    body_path.write_text(body, encoding="utf-8")
    metadata = workspace / "verified-fields.json"
    metadata.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")

    def update(path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        _helper(
            root,
            "update_analysis.py",
            [
                str(path),
                "--body",
                str(body_path),
                "--metadata",
                str(metadata),
                "--expected-sha256",
                digest,
            ],
        )

    update(candidate)
    if existing:
        if existing.read_bytes() != original:
            raise ValueError("Note changed after snapshot; no overwrite")
        # Pin the original snapshot, rather than re-snapshotting a possible concurrent edit.
        _helper(
            root,
            "update_analysis.py",
            [
                str(existing),
                "--body",
                str(body_path),
                "--metadata",
                str(metadata),
                "--expected-sha256",
                hashlib.sha256(original).hexdigest(),
            ],
        )
        destination = existing
    else:
        folder = (
            root / "notes-literature" / ("surveys" if analysis.paper_type == "survey" else "papers")
        )
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", paper.title).strip(" .")[:130]
        if not name or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name):
            name = "Paper-" + base_id(paper.arxiv_id).replace("/", "_")
        destination = folder / (name + ".md")
        # Exclusive creation: never use filename suffixes or replace an unrelated note.
        with destination.open("xb") as stream:
            stream.write(candidate.read_bytes())
    return destination
