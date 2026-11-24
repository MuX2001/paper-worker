"""Read the user's writing instructions and an example without changing the vault."""

from pathlib import Path

from .athena import BEGIN, END, vault_root


def writing_context(directory: Path) -> str:
    root = vault_root(directory)
    sources = (
        ("Vault writing and mathematical conventions", "AGENTS.md"),
        ("Paper workflow", ".agents/skills/paper-analysis/SKILL.md"),
        (
            "Full analysis specification",
            ".agents/skills/paper-analysis/references/analysis-spec.md",
        ),
        ("Shared note structure", "_template/_template_paper.md"),
    )
    parts = [
        "The following are the user's writing requirements. Apply their scientific-writing "
        "and formatting guidance. File operations, Zotero registration, note updates, migration "
        "and acceptance procedures are handled outside this analysis subprocess. Do not perform "
        "those actions, run validation scripts, or edit the vault. Return the analysis JSON only."
    ]
    for label, relative in sources:
        path = root / relative
        if path.is_file():
            parts.append(f"\n## {label}\n{path.read_text(encoding='utf-8-sig')}")

    example = root / "notes-literature/papers/Attention Is All You Need.md"
    if example.is_file():
        text = example.read_text(encoding="utf-8-sig")
        if text.count(BEGIN) == 1 and text.count(END) == 1:
            # Do not pass bibliography, Zotero identifiers, or Personal Notes as an example.
            body = text.split(BEGIN, 1)[1].split(END, 1)[0].strip()
            parts.append(
                "\n## User-selected writing example: Attention Is All You Need\n"
                "This is a STYLE AND DEPTH example, not evidence for the paper being analyzed. "
                "It uses a particular proceedings PDF. Never copy its numbers, conclusions, "
                "source-coverage claims, Zotero links, or repository findings into the new note. "
                "Even when analyzing the same title, use the exact supplied primary PDF. "
                "Match its self-contained mathematical explanations, comparison tables, "
                "claim-specific reasoning, source locators and calibrated assessment. "
                "Do not pad text to match its length.\n" + body
            )
            # Only these explicitly exemplified related notes are candidates, not the whole vault.
            related = []
            for name in ("Transformers and Attention Mechanism", "Modern Transformer Blocks"):
                matches = list(root.rglob(name + ".md"))
                if len(matches) == 1:
                    related.append(f"[[{name}]]")
            if related:
                parts.append(
                    "\nExisting link candidates; use ONLY if relevant to this paper: "
                    + ", ".join(related)
                )
    return "\n".join(parts)
