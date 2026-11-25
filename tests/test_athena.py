import hashlib
import json

import pytest

from paper_worker.athena import BEGIN, END, _helper, frontmatter
from paper_worker.exporters import export_obsidian
from paper_worker.writing_context import writing_context


def test_empty_vault_uses_bundled_defaults(tmp_path, paper, analysis):
    vault = tmp_path / "Research"
    vault.mkdir()
    path = export_obsidian(paper, analysis, vault)
    assert "## Personal Notes" in path.read_text(encoding="utf-8")
    assert "Literature MOC" not in path.read_text(encoding="utf-8")
    assert "## Shared note structure" in writing_context(vault)
    path.write_bytes(path.read_bytes() + b"My reading notes\n")
    assert export_obsidian(paper, analysis, vault) == path
    assert path.read_bytes().endswith(b"My reading notes\n")
    assert list(vault.iterdir()) == [vault / "notes-literature"]


def test_protected_content_and_existing_path(athena_vault, paper, analysis, tmp_path):
    path = export_obsidian(paper, analysis, athena_vault)
    original = (
        path.read_bytes()
        .replace(b"status: unread", b"status: reading")
        .replace(b"topics: []", b"topics: [robotics]\naliases: [My paper]\ncustom_value: keep")
    )
    original += b"Personal text stays byte-for-byte.\r\n- [ ] My task\r\n"
    path.write_bytes(original)
    moved = path.with_name("My existing filename.md")
    path.rename(moved)
    analysis.problem = "Updated managed analysis"
    analysis.note_body = analysis.note_body.replace(
        "Dense attention is expensive", "Updated managed analysis"
    )
    workspace = tmp_path / "run"
    assert export_obsidian(paper, analysis, athena_vault, workspace) == moved
    updated = moved.read_bytes()
    assert updated.split(END.encode())[1] == original.split(END.encode())[1]
    meta = frontmatter(updated)
    assert (meta["status"], meta["topics"], meta["aliases"], meta["custom_value"]) == (
        "reading",
        ["robotics"],
        ["My paper"],
        "keep",
    )
    assert (workspace / "note-before.md").read_bytes() == original
    assert "Updated managed analysis" in updated.decode()


def test_legacy_and_duplicate_refusal(athena_vault, paper, analysis):
    legacy = athena_vault / "legacy.md"
    original = b"---\narxiv_id: '1706.03762'\n---\n# Personal legacy note\n"
    legacy.write_bytes(original)
    with pytest.raises(ValueError, match="migration"):
        export_obsidian(paper, analysis, athena_vault)
    assert legacy.read_bytes() == original
    (athena_vault / "second.md").write_bytes(original)
    with pytest.raises(ValueError, match="Multiple notes"):
        export_obsidian(paper, analysis, athena_vault)


def test_no_downgrade_of_complete_analysis(athena_vault, paper, analysis):
    path = export_obsidian(paper, analysis, athena_vault)
    original = path.read_bytes().replace(
        b"analysis_status: incomplete", b"analysis_status: complete"
    )
    path.write_bytes(original)
    with pytest.raises(ValueError, match="reviewed replacement"):
        export_obsidian(paper, analysis, athena_vault)
    assert path.read_bytes() == original


def test_survey_folder_and_shared_template(athena_vault, paper, analysis, tmp_path, monkeypatch):
    monkeypatch.setattr("paper_worker.athena.DEFAULTS", tmp_path / "no-defaults")
    (athena_vault / "unrelated.md").write_text(
        "---\n- plain list\n---\nUnrelated content", encoding="utf-8"
    )
    template = athena_vault / "_template/_template_paper.md"
    template.write_bytes(template.read_bytes() + b"Shared template custom footer\n")
    assert "Shared template custom footer" in writing_context(athena_vault)
    analysis.paper_type = "survey"
    path = export_obsidian(paper, analysis, athena_vault)
    assert path.parent.name == "surveys"
    assert frontmatter(path.read_bytes())["resource_type"] == "survey"
    assert path.read_bytes().endswith(b"Shared template custom footer\n")
    assert "tags:" not in path.read_text(encoding="utf-8")


def test_helper_rejects_stale_snapshot(athena_vault, paper, analysis, tmp_path):
    path = export_obsidian(paper, analysis, athena_vault)
    old = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(path.read_bytes() + b"User edit\n")
    current = path.read_bytes()
    body = tmp_path / "body.md"
    body.write_text("## Overview\n## Paper Analysis\nUpdated", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after snapshot"):
        _helper(
            athena_vault,
            "update_analysis.py",
            [str(path), "--body", str(body), "--expected-sha256", old],
        )
    assert path.read_bytes() == current


def test_model_body_has_no_ownership_or_personal_content(analysis):
    from paper_worker.schemas import PaperAnalysis

    data = analysis.model_dump()
    for body in [
        "# Header",
        "## Overview\n## Paper Analysis\n## Personal Notes\nInvented",
        f"## Overview\n## Paper Analysis\n{BEGIN}",
    ]:
        data["note_body"] = body
        with pytest.raises(ValueError):
            PaperAnalysis.model_validate_json(json.dumps(data))
