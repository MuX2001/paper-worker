# Verification record

Windows, Python 3.13, 2026-11-26.

| Component | Evidence |
| --- | --- |
| Automated regression suite | 35 tests passed, including a generated PDF, mocked HTTP and Codex integration, Zotero deduplication, Athena export, GUI and queue tests. |
| Code and package checks | Ruff lint and format checks passed. Pip reported consistent dependencies. The isolated build produced an sdist and a wheel. |
| arXiv | The live Attention Is All You Need run downloaded the PDF and produced page-numbered text. Poppler rendered six physical pages for visual analysis. |
| GitHub | With anonymous REST quota exhausted, the live run retrieved Tensor2Tensor source excerpts from the public archive at commit bafdc1b67730430d38d6ab802cbd51f9d053ba2e. Issue titles were unavailable. |
| Zotero | The local API returned an existing personal-library item for the live paper. This exercised reuse without a Web API key. Automated tests cover creation. |
| Athena | The exporter uses the vault's shared template and update helper. Regression tests cover preservation of personal content and existing-note protections. |
| Supabase | The queue tests exercise the SDK against mock HTTP, including conditional claims and finalization. No cloud instance was used. |
| CI | A GitHub Actions workflow is included. Cross-platform CI awaits publication. |
