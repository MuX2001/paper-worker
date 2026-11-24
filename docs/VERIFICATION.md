# Verification record

Verified locally on Windows / Python 3.13 on 2026-11-24.

| Requirement | Evidence |
| --- | --- |
| CLI run / poll / gui | Typer commands implemented; run flags and error exit tested |
| arXiv normalization, metadata and PDF | Unit and mock HTTP tests; real 1706.03762 metadata/PDF downloaded |
| GitHub tree / README / issues | Mock HTTP tests cover populated/empty repositories, issue filtering, wrapped URLs, rate limits |
| Headless Codex / strict schema / retry | Real local Codex produced validated Chinese JSON; mock tests verify retry and invalid outputs |
| Obsidian notes | Real note written in Athena; Obsidian reading-view DOM confirms six sections and audit table; YAML and version overwrite tested |
| Zotero | Official preprint template fields checked; mocked creation and exact ID deduplication tested; live account write awaits credentials |
| Supabase | Claim race, success, failure and token finalization tested; actual SDK with mock HTTP verifies GET/PATCH filters and return representation; no cloud instance configured |
| GUI | Tk initialization, settings persistence, threaded execution, log delivery tested; layout requests fit the 680×520 window |
| Packaging | sdist and wheel built successfully, prompts/templates included |
| Quality | 27 tests passed; Ruff check/format and pip check passed |

The integrated regression test uses a real generated PDF and pypdf extraction, simulated arXiv/GitHub HTTP responses, and a simulated Codex process. It verifies repository tree and issue evidence reaches the analysis invocation, then checks the actual Markdown audit row and cached JSON. It does not count as live GitHub/Zotero verification.

Two earlier real paper runs completed before a PDF line-wrap extraction bug was corrected. Their notes contain paper analysis but no fetched repository context. After correction the real GitHub request correctly reaches Tensor2Tensor, but anonymous API quota is exhausted. A final live run with repository evidence is pending a GitHub token or quota reset. This is not counted as verified GitHub end-to-end success.

Zotero desktop being open does not supply Web API credentials. Supabase is optional and has no configured deployment. CI configuration is included but has not been run on GitHub; local results do not imply the cross-platform matrix has passed.

Desktop screenshot tooling failed to initialize in the host sandbox. GUI verification uses Tk tests and layout inspection; Obsidian verification uses its live reading-view DOM. An attempted screenshot captured an old visible surface and is not used as evidence.
