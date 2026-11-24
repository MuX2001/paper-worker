from types import SimpleNamespace

import httpx
import pytest

from paper_worker.config import Config, SupabaseConfig
from paper_worker.supabase_queue import poll_queue


class FakeQueue:
    def __init__(self, rows):
        self.rows = rows
        self.fail_claim = False

    def table(self, name):
        self.filters = {}
        self.payload = None
        self.count = 99
        return self

    def select(self, fields):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, field):
        return self

    def limit(self, count):
        self.count = count
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        selected = [
            row for row in self.rows if all(row.get(k) == v for k, v in self.filters.items())
        ][: self.count]
        if self.payload:
            if self.fail_claim and self.payload["status"] == "processing":
                return SimpleNamespace(data=[])
            for row in selected:
                row.update(self.payload)
        return SimpleNamespace(data=[row.copy() for row in selected])


def test_queue_success_and_failure(analysis):
    queue = FakeQueue(
        [
            {"id": "1", "status": "pending", "arxiv_input": "1706.03762"},
            {"id": "2", "status": "pending", "arxiv_input": "invalid"},
        ]
    )
    config = Config(supabase=SupabaseConfig(url="https://example.supabase.co", key="secret"))

    def runner(value, *args, **kwargs):
        if value == "invalid":
            raise ValueError("invalid secret")
        return SimpleNamespace(analysis=analysis)

    result = poll_queue(config, client=queue, runner=runner)
    assert (result.done, result.failed) == (1, 1)
    assert queue.rows[0]["result_json"]["code_status"] == "no_repo"
    assert queue.rows[1]["error_msg"] == "invalid [REDACTED]"


def test_queue_claim_race():
    queue = FakeQueue([{"id": "1", "status": "pending", "arxiv_input": "1706.03762"}])
    queue.fail_claim = True
    config = Config(supabase=SupabaseConfig(url="https://example.supabase.co", key="secret"))

    def runner(*args, **kwargs):
        raise AssertionError("Unclaimed task must not execute")

    result = poll_queue(config, client=queue, runner=runner)
    assert result.skipped == 1


def test_supabase_sdk_wire_contract(analysis):
    supabase = pytest.importorskip("supabase")
    import json

    requests = []
    row = {"id": "task-1", "status": "pending", "arxiv_input": "1706.03762"}

    def handler(request):
        requests.append(request)
        if request.method == "PATCH":
            assert "return=representation" in request.headers["prefer"]
            assert request.url.params["id"] == "eq.task-1"
            payload = json.loads(request.content)
            if payload["status"] == "processing":
                assert request.url.params["status"] == "eq.pending"
            else:
                assert request.url.params["status"] == "eq.processing"
                assert request.url.params["worker_token"] == "eq." + row["worker_token"]
            row.update(payload)
        return httpx.Response(200, json=[row.copy()])

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = supabase.create_client(
            "https://example.supabase.co",
            "test-key",
            options=supabase.ClientOptions(httpx_client=http),
        )
        config = Config(supabase=SupabaseConfig(url="https://example.supabase.co", key="test-key"))
        result = poll_queue(
            config, client=client, runner=lambda *a, **kw: SimpleNamespace(analysis=analysis)
        )
    assert result.done == 1
    assert [request.method for request in requests] == ["GET", "PATCH", "PATCH"]
