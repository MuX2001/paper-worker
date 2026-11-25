"""Bibliography registration independent of analysis, GitHub and Obsidian."""

import re
import uuid
from dataclasses import dataclass, field

import httpx

from .arxiv_client import base_id, fetch_metadata, normalize_arxiv_id
from .config import Config, ZoteroConfig
from .schemas import PaperMetadata


@dataclass
class ZoteroRegistration:
    library: str
    key: str
    uri: str
    bibliography: dict = field(default_factory=dict)

    def note_fields(self) -> dict:
        return {
            **self.bibliography,
            "zotero_library": self.library,
            "zotero_key": self.key,
            "zotero_uri": self.uri,
            "zotero_status": "linked",
        }


def _normal(value: str) -> str:
    return "".join(c for c in str(value).casefold() if c.isalnum())


def _doi(value: str) -> str:
    return re.sub(
        r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", str(value).strip(), flags=re.I
    ).casefold()


def _matches(item: dict, paper: PaperMetadata) -> bool:
    data = item.get("data", {})
    if data.get("itemType") in {"attachment", "note", "annotation"}:
        return False
    text = " ".join(str(data.get(k, "")) for k in ("url", "archiveID", "extra", "DOI"))
    arxiv_match = bool(
        re.search(r"(?<![\w.])" + re.escape(base_id(paper.arxiv_id)) + r"(?:v\d+)?(?![\d.])", text)
    )
    doi_match = bool(paper.doi and _doi(data.get("DOI", "")) == _doi(paper.doi))
    title_match = _normal(data.get("title", "")) == _normal(paper.title)
    if title_match and not (arxiv_match or doi_match):
        names = [
            c.get("name") or (c.get("firstName", "") + " " + c.get("lastName", "")).strip()
            for c in data.get("creators", [])
            if c.get("creatorType") == "author"
        ]
        years = re.search(r"\b\d{4}\b", data.get("date", ""))
        if (
            not years
            or years[0] != paper.published[:4]
            or not ({_normal(a) for a in names} & {_normal(a) for a in paper.authors})
        ):
            raise ValueError(
                "Zotero title match has ambiguous author/year identity; no new item created"
            )
    return arxiv_match or doi_match or title_match


def _registration(item: dict, config: ZoteroConfig) -> ZoteroRegistration:
    data = item["data"]
    key = item["key"]
    library_id = str(item.get("library", {}).get("id", config.library_id or "0"))
    library = ("users/" if config.library_type == "user" else "groups/") + library_id
    uri = (
        f"zotero://select/library/items/{key}"
        if config.library_type == "user"
        else f"zotero://select/groups/{library_id}/items/{key}"
    )
    fields = {}
    if data.get("title"):
        fields["title"] = data["title"]
    names = [
        c.get("name") or (c.get("firstName", "") + " " + c.get("lastName", "")).strip()
        for c in data.get("creators", [])
        if c.get("creatorType") == "author"
    ]
    if names:
        fields["authors"] = names
    year = re.search(r"\b\d{4}\b", data.get("date", ""))
    if year:
        fields["year"] = int(year[0])
    for source, target in (("DOI", "doi"), ("url", "url"), ("publicationTitle", "venue")):
        if data.get(source):
            fields[target] = data[source]
    return ZoteroRegistration(library, key, uri, fields)


def register_paper(paper: PaperMetadata, config: ZoteroConfig, *, log=print) -> ZoteroRegistration:
    if not config.enabled:
        raise ValueError(
            "Zotero Web API credentials are incomplete; use local mode for desktop Zotero"
        )
    if config.library_type == "group" and not config.library_id:
        raise ValueError("A Zotero group library ID is required")
    if config.mode == "web":
        return _register_web(paper, config, log)
    library = ("users/" if config.library_type == "user" else "groups/") + (
        config.library_id or "0"
    )
    with httpx.Client(
        base_url="http://127.0.0.1:23119/api/", timeout=40, trust_env=False
    ) as client:
        response = client.get("")
        response.raise_for_status()
        server_id = response.headers.get("Zotero-Server-ID")
        if not server_id:
            raise RuntimeError("Local writes require Zotero 10 or newer")
        client.headers["Zotero-Server-ID"] = server_id
        found = []
        start = 0
        while True:
            response = client.get(f"{library}/items/top", params={"limit": 100, "start": start})
            response.raise_for_status()
            batch = response.json()
            found.extend(item for item in batch if _matches(item, paper))
            if len(batch) < 100:
                break
            start += len(batch)
        if len(found) > 1:
            raise ValueError("Multiple Zotero items match this paper; no duplicate created")
        if found:
            log(f"Reusing Zotero item {found[0]['key']}")
            return _registration(found[0], config)
        # Public schema only; no paper content or private library data sent here.
        with httpx.Client(timeout=30) as public:
            template = public.get(
                "https://api.zotero.org/items/new", params={"itemType": "preprint"}
            )
            template.raise_for_status()
            payload = _payload(paper, config, template.json())
        log("Waiting for Zotero's local write-authorization dialog (paper-worker)…")
        authorization = client.post(
            "local/authorize", json={"appName": "paper-worker"}, timeout=300
        )
        if authorization.status_code == 403:
            raise RuntimeError("Zotero write authorization was denied; no item created")
        authorization.raise_for_status()
        key = authorization.json()["key"]
        response = client.post(
            f"{library}/items",
            json=[payload],
            headers={"Zotero-API-Key": key, "Zotero-Write-Token": uuid.uuid4().hex},
        )
        # No automatic write retry. A rerun reconciles the library before creating.
        response.raise_for_status()
        result = response.json()
        if result.get("failed"):
            raise RuntimeError(f"Zotero rejected bibliography: {result['failed']}")
        item_key = result.get("success", {}).get("0") or result.get("successful", {}).get(
            "0", {}
        ).get("key")
        if not item_key:
            raise RuntimeError(
                "Zotero creation response is uncertain; rerun to reconcile existing items"
            )
        response = client.get(f"{library}/items/{item_key}")
        response.raise_for_status()
        return _registration(response.json(), config)


def _payload(paper: PaperMetadata, config: ZoteroConfig, template: dict) -> dict:
    template.update(
        {
            "title": paper.title,
            "abstractNote": paper.abstract,
            "url": paper.url,
            "date": paper.published[:10],
            "repository": "arXiv",
            "archiveID": base_id(paper.arxiv_id),
            "extra": f"arXiv: {base_id(paper.arxiv_id)}",
            "creators": [{"creatorType": "author", "name": name} for name in paper.authors],
            "tags": [],
        }
    )
    if paper.doi:
        template["DOI"] = paper.doi
    if config.collection_key:
        template["collections"] = [config.collection_key]
    return template


def _register_web(
    paper: PaperMetadata, config: ZoteroConfig, log, client=None
) -> ZoteroRegistration:
    from pyzotero import zotero

    if client is None:
        client = zotero.Zotero(
            config.library_id, config.library_type, config.api_key.get_secret_value()
        )
    # Query identifiers separately; existing older registrations may use a title only.
    candidates = {}
    for query in (base_id(paper.arxiv_id), paper.doi, paper.title):
        if query:
            for item in client.everything(client.items(q=query, qmode="everything")):
                if _matches(item, paper):
                    candidates[item["key"]] = item
    if len(candidates) > 1:
        raise ValueError("Multiple Zotero items match this paper; no duplicate created")
    if candidates:
        item = next(iter(candidates.values()))
        log(f"Reusing Zotero item {item['key']}")
    else:
        result = client.create_items([_payload(paper, config, client.item_template("preprint"))])
        if result.get("failed"):
            raise RuntimeError(f"Zotero rejected bibliography: {result['failed']}")
        key = result.get("success", {}).get("0") or result.get("successful", {}).get("0", {}).get(
            "key"
        )
        if not key:
            raise RuntimeError("Zotero creation response is uncertain; rerun to reconcile")
        item = client.item(key)
    return _registration(item, config)


def sync_zotero(value: str, config: Config, *, log=print) -> ZoteroRegistration:
    arxiv_id = normalize_arxiv_id(value)
    log(f"Fetching bibliography for arXiv {arxiv_id}")
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        paper = fetch_metadata(arxiv_id, client)
    result = register_paper(paper, config.zotero, log=log)
    log(f"Zotero: {result.uri}")
    return result
