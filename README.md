# paper-worker

输入 arXiv URL / ID，先注册或复用 Zotero 书目条目，再下载分析论文，最后写入带 Zotero 来源链接的 Obsidian 笔记。书目注册也可独立执行，无需论文分析。支持 CLI、Tkinter GUI 和可选 Supabase 任务队列。

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
.venv/Scripts/paper-worker.exe sync-zotero https://arxiv.org/abs/1706.03762
.venv/Scripts/paper-worker.exe run 1706.03762 --no-obsidian --no-zotero
.venv/Scripts/paper-worker.exe poll --limit 3
.venv/Scripts/paper-worker.exe gui
```

所有命令支持 `--config <path>`；默认读取当前目录的 `config.yaml`。GUI 的 Settings 保存配置，Run 页按保存的配置执行。运行期间禁止重复启动与关闭，日志通过线程安全队列回到 UI 主线程。

`obsidian_vault_dir` 指向 Athena vault 根目录。程序读取 vault 的 `_template/_template_paper.md`，不另建一份生产笔记模板。新论文进入 `notes-literature/papers`，综述进入 `notes-literature/surveys`；全库按 arXiv/DOI 及经作者、年份确认的标题查重，已有笔记保留原路径。

存储正文默认英文，无 H1、无 tags，保留 `up: "[[Literature MOC]]"` 和紧随 frontmatter 的 `up:: [[Literature MOC]]`。新笔记为 `status: unread`。生成分析保持 `analysis_status: incomplete`，不会仅凭标题齐全就标为完成。

只更新 `paper-analysis:begin/end` 之间的内容及已确认的书目信息、`analysis_*` 字段。个人笔记、阅读状态、分类、topics、projects、aliases 和未知属性保留。调用现有 `__resource/paper-workflow/update_analysis.py`，使用 vault 外快照及预期哈希避免覆盖并发编辑；不额外运行独立验收校验。旧笔记缺少管理标记、多份笔记匹配或已有完整分析时停止覆盖，需要单独处理迁移或替换。

缓存按论文和运行 ID 隔离，保存 PDF、全文、元数据、仓库上下文、schema 和分析 JSON。导出失败时可从缓存检查已经完成的分析。缓存不会自动清理。

## Codex 与证据范围

默认命令为计划书指定的 `codex exec --full-auto`。程序检测 CLI 帮助；新版本不支持该参数时自动改用 `--sandbox read-only`。提示词从 stdin 传入，使用 `--output-schema` 和 `--output-last-message`，不通过 shell 拼接提示词。命令设置填写命令及选项，不填写提示词占位符。Windows 优先定位 npm 包中的原生 Codex 可执行文件。

PDF 同时抽取成 `paper.txt`，避免依赖 Codex 直接解析 PDF。GitHub 链接优先扫描摘要和首 3 / 末 2 页，未找到时补查全文；兼容链接在斜杠后的换行。最多获取 5 个候选仓库，每个包含文件树、README 和最近 10 个开放 issue 标题，不克隆或执行代码。

文件树只能证明路径存在。未读取源码时，应使用 `unclear`，不能凭文件名认定实现完整或只是占位代码。`hype_flag` 必须有具体证据支撑。模型输出仍需人工审阅；固定的是流水线和数据契约，模型文字不是逐次确定的。

无仓库时继续分析；仓库 API 请求失败会明确失败，不把无法访问误判为空仓库。JSON 解析或校验失败时附带错误重试一次；网络、权限、Codex 非零退出或超时会报告错误。

## Zotero

默认 `zotero.mode: local`，直接连接本机 Zotero。保持 Zotero 开启并启用本地 API；个人库 ID 可留空（使用本地 `users/0`），不需要云端 API key。需要创建条目时，Zotero 会弹出原生写入授权窗口。授权 key 仅保存在本次调用的内存中，不写入配置、日志或笔记。已有匹配条目直接复用，不触发写入授权。群组库需填写 group ID。

独立命令 `sync-zotero <arxiv_url_or_id>`，或 GUI 的 **Sync to Zotero Only**，只获取书目元数据、查重、注册条目并返回 Zotero 链接；不下载 PDF、不访问 GitHub、不调用 Codex、不创建 Obsidian 笔记。注册保存标题、作者、摘要、来源和日期等书目字段，不发送分析正文、代码审查结论或分析标签。

完整 `run` 流程同样先注册 Zotero，再进行论文分析，最后写 Obsidian。笔记的书目字段优先采用 Zotero 返回数据，并写入 `zotero_library`、`zotero_key`、`zotero_uri`、`zotero_status: linked`，Overview 中包含 **Open in Zotero** 链接。后续分析失败不会回滚已经成功注册的 Zotero 条目；重跑时先查重复用。勾选同步却连接失败时会停止，不再静默生成缺少关联的笔记；显式 `--no-zotero` 仍允许跳过注册。

可选 `zotero.mode: web` 才需要 Library ID、Library Type 和云端 API Key。不会自动上传 PDF；单独书目注册与附件存储是不同操作。

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

提示词位于 `src/paper_worker/prompts/`。运行时读取 Athena 的 `AGENTS.md`、paper-analysis skill、分析规范、共享模板，以及用户指定的 `Attention Is All You Need.md` 管理区域作为写作深度范例；不传入该笔记的 Properties 或 Personal Notes。范例不作为待分析论文的事实来源，即使标题相同，也不能跨版本套用结果。

`note_body` 是完整 Paper Analysis，短字段仅作分析索引。没有完整正文时拒绝导出，不再将短摘要拼成正式论文笔记。页码标记辅助定位原 PDF；数学定义、维度、训练/推理细节、定量比较、消融、针对具体主张的证据评述及复现资产解释均按原 workflow 要求撰写。不同论文类型保留各自适用的分析维度。

当前预采集仍只有仓库目录、README 和 issue 标题，不能声称完成了原范例那种固定 commit 的源码、权重、数据与评测逐项检查；没有实际查看图表也不能声称视觉审阅。生成指令改进不等同于已完成真实论文内容验收。arXiv 下载固定到 API 返回的确切版本。

Git 默认分支为 `main`。尚未指定远端，上传时可自行添加：

```powershell
git remote add origin <your-repository-url>
git push -u origin main
```
