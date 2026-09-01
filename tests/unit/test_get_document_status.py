import decimal
import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("get_document_status")


def _event(document_id):
    return {"pathParameters": {"documentId": document_id}}


def test_returns_item_as_json(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {
        "Item": {"documentId": "doc-1", "status": "READY_FOR_SUBMISSION", "confidence": decimal.Decimal("91.5")}
    }
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["documentId"] == "doc-1"
    assert body["confidence"] == 91.5
    fake_table.get_item.assert_called_once_with(Key={"documentId": "doc-1"}, ConsistentRead=True)


def test_returns_404_when_not_found(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("missing-doc"), None)

    assert result["statusCode"] == 404
