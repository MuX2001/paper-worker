import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from pypdf import PdfReader

from .schemas import PaperMetadata

ID_PATTERN = r"(?:\d{4}\.\d{4,5}|[a-zA-Z][a-zA-Z.\-]+/\d{7})(?:v[1-9]\d*)?"


def normalize_arxiv_id(value: str) -> str:
    value = value.strip()
    if value.startswith(("https://", "http://")):
        url = urlparse(value)
        if url.hostname not in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            raise ValueError("Expected an arxiv.org URL")
        value = re.sub(r"^/(abs|pdf|html)/", "", unquote(url.path))
    value = re.sub(r"^arxiv:\s*", "", value, flags=re.I)
    value = value.removesuffix(".pdf")
    if not re.fullmatch(ID_PATTERN, value):
        raise ValueError("Invalid arXiv ID or URL")
    return value


def base_id(value: str) -> str:
    return re.sub(r"v\d+$", "", normalize_arxiv_id(value))


def fetch_metadata(arxiv_id: str, client: httpx.Client) -> PaperMetadata:
    response = client.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id})
    response.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = ET.fromstring(response.content).find("a:entry", ns)
    if entry is None:
        raise ValueError(f"arXiv paper not found: {arxiv_id}")
    entry_id = entry.findtext("a:id", "", ns)
    if "/errors" in entry_id:
        raise ValueError("arXiv returned an API error")
    resolved_id = normalize_arxiv_id(entry_id)
    if base_id(resolved_id) != base_id(arxiv_id):
        raise ValueError("arXiv returned a different paper identity")
    if re.search(r"v\d+$", arxiv_id) and resolved_id != arxiv_id:
        raise ValueError("arXiv returned a different revision than requested")
    metadata = PaperMetadata(
        arxiv_id=resolved_id,
        title=" ".join(entry.findtext("a:title", "", ns).split()),
        authors=[a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)],
        abstract=" ".join(entry.findtext("a:summary", "", ns).split()),
        published=entry.findtext("a:published", "", ns),
        url=f"https://arxiv.org/abs/{resolved_id}",
        pdf_url=f"https://arxiv.org/pdf/{resolved_id}",
        doi=entry.findtext("{http://arxiv.org/schemas/atom}doi", ""),
    )
    return metadata


def fetch_paper(arxiv_id: str, workspace: Path, client: httpx.Client) -> tuple[PaperMetadata, Path]:
    metadata = fetch_metadata(arxiv_id, client)
    return metadata, download_pdf(metadata, workspace, client)


def download_pdf(metadata: PaperMetadata, workspace: Path, client: httpx.Client) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    pdf_path = workspace / "paper.pdf"
    response = client.get(metadata.pdf_url)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF-"):
        raise ValueError("arXiv download is not a PDF")
    pdf_path.write_bytes(response.content)
    return pdf_path


def extract_text(pdf_path: Path) -> tuple[str, str]:
    reader = PdfReader(pdf_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    indices = sorted(
        set(range(min(3, len(pages)))) | set(range(max(0, len(pages) - 2), len(pages)))
    )
    numbered = [f"--- PDF page {i + 1} ---\n{text}" for i, text in enumerate(pages)]
    return "\n\n".join(numbered), "\n\n".join(pages[i] for i in indices)
