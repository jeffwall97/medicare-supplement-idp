import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("list_documents")


def test_sorts_by_ingested_at_descending(monkeypatch):
    fake_table = MagicMock()
    fake_table.scan.return_value = {
        "Items": [
            {"documentId": "doc-1", "ingestedAt": "2026-01-01T00:00:00+00:00"},
            {"documentId": "doc-3", "ingestedAt": "2026-01-03T00:00:00+00:00"},
            {"documentId": "doc-2", "ingestedAt": "2026-01-02T00:00:00+00:00"},
        ]
    }
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"queryStringParameters": None}, None)

    body = json.loads(result["body"])
    assert [d["documentId"] for d in body["documents"]] == ["doc-3", "doc-2", "doc-1"]


def test_respects_limit_query_param(monkeypatch):
    fake_table = MagicMock()
    fake_table.scan.return_value = {
        "Items": [{"documentId": f"doc-{i}", "ingestedAt": f"2026-01-{i:02d}T00:00:00+00:00"} for i in range(1, 6)]
    }
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"queryStringParameters": {"limit": "2"}}, None)

    body = json.loads(result["body"])
    assert len(body["documents"]) == 2
    assert body["documents"][0]["documentId"] == "doc-5"


def test_invalid_limit_falls_back_to_default(monkeypatch):
    fake_table = MagicMock()
    fake_table.scan.return_value = {"Items": []}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"queryStringParameters": {"limit": "not-a-number"}}, None)

    assert result["statusCode"] == 200


def test_status_filter_queries_status_index_instead_of_scanning(monkeypatch):
    fake_table = MagicMock()
    fake_table.query.return_value = {
        "Items": [
            {"documentId": "doc-2", "status": "NEEDS_REVIEW", "ingestedAt": "2026-01-02T00:00:00+00:00"},
            {"documentId": "doc-1", "status": "NEEDS_REVIEW", "ingestedAt": "2026-01-01T00:00:00+00:00"},
        ]
    }
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"queryStringParameters": {"status": "NEEDS_REVIEW"}}, None)

    body = json.loads(result["body"])
    assert [d["documentId"] for d in body["documents"]] == ["doc-2", "doc-1"]
    fake_table.scan.assert_not_called()

    query_kwargs = fake_table.query.call_args.kwargs
    assert query_kwargs["IndexName"] == "StatusIndex"
    assert query_kwargs["ScanIndexForward"] is False
    assert query_kwargs["Limit"] == 50


def test_status_filter_respects_limit(monkeypatch):
    fake_table = MagicMock()
    fake_table.query.return_value = {"Items": []}
    monkeypatch.setattr(app, "table", fake_table)

    app.handler({"queryStringParameters": {"status": "SUBMITTED", "limit": "5"}}, None)

    assert fake_table.query.call_args.kwargs["Limit"] == 5
