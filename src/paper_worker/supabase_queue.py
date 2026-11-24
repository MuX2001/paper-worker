import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Config
from .pipeline import run_pipeline


@dataclass
class PollResult:
    done: int = 0
    failed: int = 0
    skipped: int = 0


def poll_queue(
    config: Config,
    limit: int = 3,
    *,
    log=print,
    client=None,
    runner=run_pipeline,
    obsidian=True,
    zotero=True,
) -> PollResult:
    if not config.supabase.enabled:
        raise ValueError("Supabase URL and key are not configured")
    if limit < 1:
        raise ValueError("limit must be positive")
    if client is None:
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError(
                'Install queue support with pip install "paper-worker[queue]"'
            ) from exc
        client = create_client(config.supabase.url, config.supabase.key.get_secret_value())
    tasks = (
        client.table("paper_tasks")
        .select("*")
        .eq("status", "pending")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
    )
    summary = PollResult()
    for task in tasks:
        claim = str(uuid.uuid4())
        claimed = (
            client.table("paper_tasks")
            .update(
                {
                    "status": "processing",
                    "worker_token": claim,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "error_msg": None,
                }
            )
            .eq("id", task["id"])
            .eq("status", "pending")
            .execute()
            .data
        )
        if not claimed:
            summary.skipped += 1
            continue
        log(f"Queue task: {task['id']}")
        try:
            result = runner(task["arxiv_input"], config, obsidian=obsidian, zotero=zotero, log=log)
            update = {
                "status": "done",
                "code_status": result.analysis.code_status,
                "hype_flag": result.analysis.hype_flag,
                "result_json": result.analysis.model_dump(mode="json"),
                "error_msg": None,
            }
        except Exception as exc:
            message = str(exc)
            for secret in (
                config.github_token.get_secret_value(),
                config.zotero.api_key.get_secret_value(),
                config.supabase.key.get_secret_value(),
            ):
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            update = {"status": "failed", "error_msg": message[:2000]}
            log(f"Task failed: {message[:2000]}")
        update["finished_at"] = datetime.now(timezone.utc).isoformat()
        updated = (
            client.table("paper_tasks")
            .update(update)
            .eq("id", task["id"])
            .eq("worker_token", claim)
            .eq("status", "processing")
            .execute()
            .data
        )
        if not updated:
            raise RuntimeError(f"Lost queue claim while finalizing task {task['id']}")
        if update["status"] == "done":
            summary.done += 1
        else:
            summary.failed += 1
    log(f"Queue finished: done={summary.done}, failed={summary.failed}, skipped={summary.skipped}")
    return summary
