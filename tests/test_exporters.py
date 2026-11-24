from unittest.mock import Mock

import yaml

from paper_worker.config import ZoteroConfig
from paper_worker.exporters import export_obsidian, export_zotero


def test_note(tmp_path, paper, analysis):
    path = export_obsidian(paper, analysis, tmp_path)
    text = path.read_text(encoding="utf-8")
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert metadata["arxiv_id"] == paper.arxiv_id
    assert metadata["hype_flag"] is False
    assert metadata["tags"] == analysis.tags
    assert analysis.tldr in text
    paper.arxiv_id = "1706.03762v2"
    assert export_obsidian(paper, analysis, tmp_path) == path
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_zotero_create_and_duplicate(paper, analysis):
    client = Mock()
    client.everything.return_value = []
    client.item_template.return_value = {}
    client.create_items.return_value = {"success": {"0": "ITEM123"}, "failed": {}}
    config = ZoteroConfig(library_id="123", api_key="secret")
    assert export_zotero(paper, analysis, config, client) == "ITEM123"
    payload = client.create_items.call_args.args[0][0]
    assert {"tag": "code:no_repo"} in payload["tags"]
    assert payload["extra"] == "arXiv: 1706.03762"
    client.reset_mock()
    client.everything.return_value = [{"key": "EXISTING", "data": {"extra": "arXiv: 1706.03762v3"}}]
    assert export_zotero(paper, analysis, config, client) == "EXISTING"
    client.create_items.assert_not_called()
