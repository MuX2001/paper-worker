# paper-worker

输入 arXiv URL / ID，在本地完成论文下载、GitHub 预审、Codex 结构化分析、Obsidian 笔记归档及可选 Zotero 同步。支持 CLI、Tkinter GUI 和可选 Supabase 任务队列。

## 安装

需要 Python 3.10+、已安装并完成登录的 Codex CLI。GUI 需要 Python 的 Tk 支持（Windows 官方安装包通常自带，Linux 可安装系统 `python3-tk`）。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev,queue]"
Copy-Item config.example.yaml config.yaml
.venv/Scripts/paper-worker.exe gui
```

macOS / Linux 使用 `.venv/bin/python` 和 `.venv/bin/paper-worker`。不需要激活虚拟环境。如果已有 `config.yaml`，保留它，不要覆盖。配置文件、缓存、API key 和生成笔记均不纳入 Git。

## 使用

```powershell
.venv/Scripts/paper-worker.exe run https://arxiv.org/abs/1706.03762 --no-zotero
.venv/Scripts/paper-worker.exe run 1706.03762 --no-obsidian --no-zotero
.venv/Scripts/paper-worker.exe poll --limit 3
.venv/Scripts/paper-worker.exe gui
```

所有命令支持 `--config <path>`；默认读取当前目录的 `config.yaml`。GUI 的 Settings 保存配置，Run 页按保存的配置执行。运行期间禁止重复启动与关闭，日志通过线程安全队列回到 UI 主线程。

`obsidian_vault_dir` 是笔记输出目录，可设为 vault 内专用子目录，如 `Athena/Papers/arXiv`。生成文件采用 `arxiv-<ID>.md`，同一论文的不同版本更新同一份笔记。生成笔记会被重新渲染；个人批注建议放在另一份笔记中并使用 wikilink 引用。

缓存按论文和运行 ID 隔离，保存 PDF、全文、元数据、仓库上下文、schema 和分析 JSON。导出失败时可从缓存检查已经完成的分析。缓存不会自动清理。

## Codex 与证据范围

默认命令为计划书指定的 `codex exec --full-auto`。程序检测 CLI 帮助；新版本不支持该参数时自动改用 `--sandbox read-only`。提示词从 stdin 传入，使用 `--output-schema` 和 `--output-last-message`，不通过 shell 拼接提示词。命令设置填写命令及选项，不填写提示词占位符。Windows 优先定位 npm 包中的原生 Codex 可执行文件。

PDF 同时抽取成 `paper.txt`，避免依赖 Codex 直接解析 PDF。GitHub 链接优先扫描摘要和首 3 / 末 2 页，未找到时补查全文；兼容链接在斜杠后的换行。最多获取 5 个候选仓库，每个包含文件树、README 和最近 10 个开放 issue 标题，不克隆或执行代码。

文件树只能证明路径存在。未读取源码时，应使用 `unclear`，不能凭文件名认定实现完整或只是占位代码。`hype_flag` 必须有具体证据支撑。模型输出仍需人工审阅；固定的是流水线和数据契约，模型文字不是逐次确定的。

无仓库时继续分析；仓库 API 请求失败会明确失败，不把无法访问误判为空仓库。JSON 解析或校验失败时附带错误重试一次；网络、权限、Codex 非零退出或超时会报告错误。

## Zotero

在 Settings 填写 Library ID、Library Type (`user` / `group`) 和 API Key，Collection Key 可选。个人 Library ID 和 API key 可在 [Zotero API 设置](https://www.zotero.org/settings/keys) 获取，key 需具有目标库写入权限。**桌面 Zotero 已启动不代表 Web API 已配置**。

未配置时跳过并记录原因。配置后创建 `preprint` 条目，保存 arXiv URL、作者、摘要、日期和标签，含 `code:<status>` 与可选 `hype-warning`。创建前检索并精确匹配 arXiv ID（忽略版本号）；已存在条目保持不变。Web API 写入后由 Zotero 自己的同步机制同步至桌面。不会自动上传 PDF。

## Supabase（可选）

安装 `.[queue]`，在项目 SQL editor 执行 [sql/supabase.sql](sql/supabase.sql)，配置 URL 和 key。表名 `paper_tasks`，输入字段为 `arxiv_input`。`poll` 每次处理一个有限批次，不是常驻服务；可由外部任务调度器定期调用。

状态：`pending → processing → done / failed`。worker 用带 `status=pending` 条件的原子更新领取任务，并用唯一 token 回写，防止多个 worker 同时领取。成功回写 `code_status`、`hype_flag`、`result_json`；失败写 `error_msg`。

SQL 默认启用 RLS 且不授予匿名访问。推荐服务端 worker 使用 service role key；如果使用 anon key，需要按自己的认证方案建立 RLS 策略。不要将 service key 放进网页。前端实现不属于本项目范围。

worker 崩溃后，确认进程已停止，再将该任务重置为 `pending` 并清空 `worker_token`。不会自动过期抢占仍在执行的任务。Obsidian 重跑更新生成文件，Zotero 重跑去重；不同队列行同时包含同一论文时，Zotero 检索与创建之间仍可能竞态，部署时应避免重复入队。

## 开发与测试

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check src tests
.venv/Scripts/ruff.exe format --check src tests
.venv/Scripts/python.exe -m build
```

测试默认不调用外部服务或 Codex。覆盖 arXiv 解析与 HTTP、PDF 换行链接、GitHub API、Codex JSON 提取及重试、配置、Jinja2/YAML、Zotero 去重、队列领取/失败与 CLI/GUI。无显示器的环境会跳过 GUI 测试；Windows 本机可直接运行。

提示词和模板位于 `src/paper_worker/prompts/` 与 `src/paper_worker/templates/`，随 wheel 打包，安装后无需依赖仓库工作目录。其余模块与 `PROJECT_PLAN.md` 对应。

Git 默认分支为 `main`。尚未指定远端，上传时可自行添加：

```powershell
git remote add origin <your-repository-url>
git push -u origin main
```
