# paper-worker

输入 arXiv 链接或 ID，先在 Zotero 创建或复用书目条目，再用 Codex 分析论文，将带 Zotero 链接的 Markdown 笔记写入 Athena。

## Quick Start

在项目根目录打开 PowerShell，启动已启用本地 API 的 Zotero，并确认 Codex CLI 已登录。首次运行时在 GUI 的 Settings 选好 Athena 根目录并保存。

```powershell
if (!(Test-Path '.venv')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -e ".[queue]"
if (!(Test-Path 'Paper Worker.lnk')) { powershell -NoProfile -ExecutionPolicy Bypass -File .\create-shortcut.ps1 }
Invoke-Item '.\Paper Worker.lnk'
.\.venv\Scripts\paper-worker.exe run 1706.03762
```

## Config

根目录的 `config.yaml` 可在 GUI 的 Settings 中保存，完整格式见 [config.example.yaml](config.example.yaml)。

| 字段 | 何时填写 | 值 |
| --- | --- | --- |
| `obsidian_vault_dir` | 写笔记时必填 | Athena 根目录 |
| `zotero.mode` / `zotero.library_type` | 选填 | 默认 `local` / `user`，可切换为 `web` / `group` |
| `zotero.library_id` | Web 模式或群组库必填 | 用户或群组 ID |
| `zotero.api_key` | Web 模式必填 | Zotero API key |
| `zotero.collection_key` | 选填 | 目标分类的 key |
| `supabase.url` / `supabase.key` | 用 `poll` 时必填 | 项目 URL 和密钥，先执行[建表 SQL](sql/supabase.sql) |
| `github_token` | 选填 | GitHub API token |
| `cache_dir` | 选填 | 默认 `~/.cache/paper-worker` |
| `codex_command` / `codex_timeout` | 选填 | 默认 `codex exec --full-auto` / 900 秒 |

## Commands

```powershell
.\.venv\Scripts\paper-worker.exe run 1706.03762 --no-obsidian --no-zotero  # 仅分析，结果存入缓存
.\.venv\Scripts\paper-worker.exe poll --limit 3                          # 最多处理 3 个队列任务
.\.venv\Scripts\paper-worker.exe gui                                     # 打开桌面界面
```
