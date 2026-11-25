import re
import shutil
import subprocess
import sys
from pathlib import Path


def render_figures(pdf: Path, text: str, log=print) -> list[Path]:
    """Attach up to six physical pages with figure or table captions."""
    renderer = shutil.which("pdftoppm")
    if not renderer:
        log("Page images unavailable: install Poppler pdftoppm for visual evidence")
        return []
    sections = re.split(r"(?m)^--- PDF page (\d+) ---\n", text)
    ranked = []
    for number, body in zip(sections[1::2], sections[2::2]):
        captions = re.findall(r"(?im)^\s*(?:fig(?:ure)?\.?|table)\s+[\dIVX]+\s*[:.]", body)
        if captions or not body.strip():
            ranked.append((-len(captions), int(number)))
    images = []
    for page in sorted(page for _, page in sorted(ranked)[:6]):
        prefix = pdf.parent / f"visual-page-{page}"
        result = subprocess.run(
            [
                renderer,
                "-f",
                str(page),
                "-l",
                str(page),
                "-singlefile",
                "-scale-to",
                "1700",
                "-png",
                str(pdf),
                str(prefix),
            ],
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            capture_output=True,
            timeout=90,
            check=False,
        )
        image = prefix.with_suffix(".png")
        if result.returncode == 0 and image.is_file():
            images.append(image)
        else:
            log(f"Could not render PDF page {page}")
    return images
