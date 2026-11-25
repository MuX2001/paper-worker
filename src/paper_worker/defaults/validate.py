"""Mechanical paper-note validation; needs PyYAML. Does not judge analysis quality."""

import argparse
import re
from pathlib import Path

import yaml

BEGIN = "<!-- paper-analysis:begin -->"
END = "<!-- paper-analysis:end -->"
MUTABLE = set(
    "title authors year venue doi arxiv_id url zotero_library zotero_key zotero_uri zotero_status analysis_status analysis_source analysis_version analysis_date analysis_spec".split()
)
MUTABLE.update(("zotero_attachment_key", "attachment_status", "analysis_source_sha256"))


def split(text):
    match = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not match:
        raise ValueError("Missing YAML frontmatter")
    meta = yaml.safe_load(match[1])
    if not isinstance(meta, dict):
        raise ValueError("Frontmatter must be a mapping")
    body = text[match.end() :]
    if body.count(BEGIN) != 1 or body.count(END) != 1:
        raise ValueError(
            "Exactly one managed region is required; legacy notes need migration review"
        )
    start, end = body.index(BEGIN), body.index(END)
    if start >= end:
        raise ValueError("Reversed region markers")
    return meta, body[:start], body[end + len(END) :], body[start:end]


def validate(text, before=None):
    meta, prefix, suffix, region = split(text)
    errors = []
    for key in ("type", "resource_type", "status", "analysis_status", "analysis_spec"):
        if not meta.get(key):
            errors.append(f"Missing property: {key}")
    if meta.get("type") != "literature":
        errors.append("type must be literature")
    if "tags" in meta or re.search(r"^tags?::", text, re.M):
        errors.append("Tags are prohibited")
    if re.search(r"^# ", text, re.M):
        errors.append("No H1 in Paper Notes")
    if "## Personal Notes" not in suffix:
        errors.append("Personal Notes must follow managed region")
    if "## Overview" not in region or "## Paper Analysis" not in region:
        errors.append("Missing overview/analysis sections")
    if meta.get("analysis_status") not in ("pending", "incomplete", "complete"):
        errors.append("Invalid analysis status")
    if meta.get("analysis_status") in ("complete", "incomplete"):
        for key in ("title", "analysis_source", "analysis_version", "analysis_date"):
            if not meta.get(key):
                errors.append(f"Missing analysis provenance: {key}")
    if meta.get("zotero_status") == "linked" and not all(
        meta.get(k) for k in ("zotero_library", "zotero_key", "zotero_uri")
    ):
        errors.append("Linked Zotero status requires verified association fields")
    if meta.get("attachment_status") == "stored_verified":
        if not meta.get("zotero_attachment_key") or not re.fullmatch(
            r"[0-9a-f]{64}", str(meta.get("analysis_source_sha256", ""))
        ):
            errors.append("Verified attachment requires item key and source SHA-256")
    if before is not None:
        old, old_prefix, old_suffix, _ = split(before)
        if (prefix, suffix) != (old_prefix, old_suffix):
            errors.append("Protected body text changed")
        if {k: v for k, v in meta.items() if k not in MUTABLE} != {
            k: v for k, v in old.items() if k not in MUTABLE
        }:
            errors.append("Protected metadata changed")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("note", type=Path)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    try:
        # Preserve line endings for body comparison.
        text = args.note.read_bytes().decode("utf-8-sig")
        before = args.before.read_bytes().decode("utf-8-sig") if args.before else None
        errors = validate(text, before)
    except (ValueError, yaml.YAMLError) as exc:
        errors = [str(exc)]
    print(
        "\n".join(errors)
        if errors
        else "PASS (structure/protection only; source audit still required)"
    )
    raise SystemExit(bool(errors))
