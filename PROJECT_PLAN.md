下面这份计划书是直接按 **AI Coding Agent（Codex）的执行视角**写的。你可以直接保存为仓库根目录下的 `PROJECT_PLAN.md`，然后让 Codex 读取它并按 Phase 逐步实现。

GUI 选了 Python 标准库自带的 `tkinter (ttk)`——零额外依赖、跨平台不踩坑、Codex 写起来不会因为第三方 GUI 库版本变更而报错。

---

```markdown
# Project Plan: `paper-worker` (Local arXiv Processing & Archiving Pipeline)

## 1. Project Overview
Build a lightweight, deterministic local Python tool (`paper-worker`) that takes an **arXiv URL or ID**, downloads the paper, audits its linked GitHub repository (without cloning), invokes the local **Codex CLI** in headless mode to produce a strict structured JSON summary & code audit (eliminating conversational disclaimers), and outputs:
1. A clean **Obsidian Markdown note** (via Jinja2 template).
2. A **Zotero library entry** with auto-generated tags (via Zotero Web API).
3. Optional status sync with a **Supabase** task queue (for remote triggering from a web frontend).

The tool must support both **CLI execution** and a **minimal desktop GUI** for configuration and manual/queue execution.

---

## 2. Tech Stack & Constraints
- **Language:** Python 3.10+
- **CLI:** `typer`
- **Minimal GUI:** Python standard library `tkinter` (`ttk`) — zero external GUI dependencies, runs long tasks in a background `threading.Thread` to keep UI responsive.
- **Data Validation:** `pydantic` (v2)
- **HTTP & Parsing:** `httpx`, `pypdf` (for extracting GitHub URLs from PDF text), `xml.etree.ElementTree` (for arXiv Atom API)
- **Templating & Config:** `jinja2`, `pyyaml`
- **Integrations:** `pyzotero` (Zotero API), `supabase` (optional, only active if configured)
- **Design Principle:** Deterministic pipeline. Do NOT use heavy agent frameworks (no LangChain/Dify). Codex CLI is called strictly as a subprocess for structured extraction.

---

## 3. Directory Structure
```text
paper-worker/
├── pyproject.toml
├── config.example.yaml          # Sample config (git-tracked)
├── config.yaml                  # User local config (git-ignored)
├── prompts/
│   └── audit_prompt.txt         # Strict JSON-only instruction for Codex CLI
├── templates/
│   └── obsidian_note.md.j2      # Jinja2 template for Obsidian Markdown
└── src/
    └── paper_worker/
        ├── __init__.py
        ├── cli.py               # Typer CLI entrypoints (`run`, `poll`, `gui`)
        ├── gui.py               # Minimal Tkinter GUI (Quick Run + Settings)
        ├── config.py            # Load/save config.yaml via Pydantic
        ├── schemas.py           # Strict Pydantic models for Codex JSON output
        ├── pipeline.py          # Main orchestrator (steps 1 to 6)
        ├── arxiv_client.py      # Parse arXiv URL/ID, fetch metadata & PDF
        ├── github_audit.py      # Extract GitHub URL, fetch file tree & README via API
        ├── codex_runner.py      # Subprocess wrapper for headless Codex CLI + retry
        ├── exporters.py         # Obsidian Markdown writer & Zotero (`pyzotero`) sync
        └── supabase_queue.py    # Optional: poll `pending` tasks & update status

```

---

## 4. Core Data Schema (`schemas.py`)

Codex CLI MUST output JSON conforming to this exact Pydantic schema (no prose, no disclaimers):

```python
class CodeAuditItem(BaseModel):
    paper_module: str            # e.g., "Sec 3.2 Gaussian Fusion"
    file_path: str               # e.g., "models/fusion.py" or "N/A"
    status: Literal["exists", "missing", "stub_only", "unclear"]

class ExperimentSummary(BaseModel):
    datasets: list[str]
    key_results: str             # Concise quantitative takeaway
    red_flags: str               # Missing baselines, synthetic-only, ablation gaps, or "None"

class PaperAnalysis(BaseModel):
    tldr: str                    # <= 50 Chinese chars, direct, no "本文提出了一种创新的..."
    problem: str                 # Concrete limitation of prior work
    method_details: list[str]    # Bullet-level technical specifics
    experiments: ExperimentSummary
    tags: list[str]              # Lowercase, hyphenated tags for Obsidian/Zotero
    repo_url: str | None = None
    code_status: Literal["complete", "partial", "empty_repo", "no_repo"]
    code_audit: list[CodeAuditItem]
    missing_assets: list[str]    # e.g., ["pretrained weights", "training script"]
    hype_flag: bool              # True if claims significantly exceed code/experiment evidence
    hype_reason: str = ""        # Required only if hype_flag is True

```

---

## 5. Processing Pipeline (`pipeline.py`)

Given an input string (e.g., `https://arxiv.org/abs/2601.12345`, `https://arxiv.org/pdf/2601.12345.pdf`, or `2601.12345`):

1. **Normalize Input (`arxiv_client.py`):**
* Regex-extract canonical `arxiv_id` (strip version suffix if needed or preserve).
* Fetch title, authors, abstract, published date via arXiv API.
* Download PDF to a temporary workspace (`~/.cache/paper-worker/<arxiv_id>/paper.pdf`).


2. **GitHub Pre-Audit (`github_audit.py`):**
* Scan abstract + first 3 pages & last 2 pages of PDF text for `github.com/<owner>/<repo>` URLs.
* If found, call GitHub REST API (with optional PAT from config to avoid rate limits) to fetch:
* Recursive file tree (`/git/trees/{default_branch}?recursive=1`)
* `README.md` content
* Recent open issues titles (top 10, check for reproduction red flags)


* Save combined repo context to `repo_context.txt` in the temp workspace. Do NOT `git clone`.


3. **Headless Codex Execution (`codex_runner.py`):**
* Build command from `config.yaml` (default: `codex exec --full-auto "<prompt>"`).
* Pass paths to `paper.pdf`, `repo_context.txt` (if any), and the JSON schema/prompt.
* Capture stdout, extract JSON block via regex, validate with `PaperAnalysis.model_validate_json()`.
* If JSON parsing or validation fails, retry once with the validation error appended.


4. **Export to Obsidian (`exporters.py`):**
* Render `templates/obsidian_note.md.j2` with arXiv metadata + `PaperAnalysis`.
* Write to `<obsidian_vault_dir>/<sanitized_filename>.md` with YAML frontmatter (`arxiv_id`, `code_status`, `hype_flag`, `tags`, `repo_url`).


5. **Export to Zotero (`exporters.py`):**
* If Zotero credentials are configured, create a Zotero item (type `preprint` or `journalArticle`), attach arXiv URL, and apply tags (`tags` + `code:<code_status>` + optional `hype-warning`).
* Check for duplicate `arxiv_id` before creating.


6. **Optional Supabase Sync (`supabase_queue.py`):**
* When triggered via queue polling, update task row `status` to `done` (or `failed` with `error_msg`) and write back `code_status`, `hype_flag`, and `result_json`.



---

## 6. CLI & Minimal GUI Specification

### CLI (`cli.py`)

* `paper-worker run <arxiv_url_or_id> [--no-zotero] [--no-obsidian]`
* Runs the pipeline for a single paper and prints step-by-step progress.


* `paper-worker poll [--limit 3]`
* Fetches `pending` tasks from Supabase `paper_tasks` table and runs the pipeline for each.


* `paper-worker gui`
* Launches the minimal Tkinter GUI.



### Minimal GUI (`gui.py`)

A compact `tkinter.ttk` window (approx. 680x520) with two tabs (`ttk.Notebook`):

1. **Tab 1: Run**
* **Input:** Single-line entry for `arXiv URL / ID`.
* **Options:** Checkboxes for `Save to Obsidian` and `Sync to Zotero` (default checked).
* **Actions:**
* `[Run Paper]` button: executes pipeline in a background thread.
* `[Poll Supabase Queue]` button: runs pending remote tasks (disabled if Supabase not configured).


* **Log Output:** Read-only scrollable text box showing real-time step logs, final Obsidian file path, and `code_status` / `hype_flag` summary.


2. **Tab 2: Settings**
* Form fields mapped directly to `config.yaml`:
* Obsidian Output Directory (with `[Browse...]` folder picker)
* Codex CLI Command Template (default: `codex exec --full-auto`)
* GitHub Token (masked)
* Zotero Library ID, Library Type (`user`/`group`), API Key (masked), Collection Key (optional)
* Supabase URL & Service/Anon Key (optional, masked)


* `[Save Settings]` button that validates and writes `config.yaml`.



---

## 7. Implementation Milestones (For Codex)

Execute strictly in this order and verify each phase before moving on:

* **Phase 1 (Core & CLI):** Setup `pyproject.toml`, `config.py`, `schemas.py`, `arxiv_client.py`, `github_audit.py`, `codex_runner.py`, `templates/obsidian_note.md.j2`, and `cli.py` (`run` command). Verify with a dry-run/mock test.
* **Phase 2 (Exporters & Queue):** Implement `exporters.py` (Obsidian + `pyzotero`) and `supabase_queue.py` (`poll` command).
* **Phase 3 (Minimal GUI):** Implement `gui.py` with threaded execution and live log streaming to the Tkinter text widget; wire `paper-worker gui`.
* **Phase 4 (Verification):** Add unit tests (`pytest`) for arXiv URL parsing, GitHub URL extraction, JSON extraction/validation, and Jinja2 rendering.

```

---

### 交给 Codex 时的实操建议
1. 把上面代码块存为 `PROJECT_PLAN.md`，在空目录里执行 `git init`。
2. 给 Codex 的第一条指令直接写：
   > 阅读 `PROJECT_PLAN.md`，先严格按照 **Phase 1** 搭建项目骨架和核心模块，完成后告诉我怎么用一条真实 arXiv 链接测试。不要跳过 Phase 直接写 GUI。
3. 等 Phase 1 用真实论文跑通、你确认 Obsidian 笔记格式和 JSON 没废话之后，再让它继续写 Phase 2 和 Phase 3（GUI）。这样最不容易翻车。

```