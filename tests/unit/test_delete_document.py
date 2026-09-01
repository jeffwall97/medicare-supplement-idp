import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")
os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("delete_document")


def _event(document_id):
    return {"pathParameters": {"documentId": document_id}}


def test_returns_404_when_not_found(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("missing-doc"), None)

    assert result["statusCode"] == 404


def test_returns_409_when_uploaded(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": {"documentId": "doc-1", "status": "UPLOADED"}}
    monkeypatch.setattr(app, "table", fake_table)
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 409
    fake_table.delete_item.assert_not_called()
    fake_s3.delete_object.assert_not_called()


def test_returns_409_when_processing(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": {"documentId": "doc-1", "status": "PROCESSING"}}
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "s3", MagicMock())

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 409


def test_deletes_raw_and_processed_objects_and_the_table_item(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {
        "Item": {
            "documentId": "doc-1",
            "status": "SUBMITTED",
            "sourceBucket": "raw-bucket",
            "sourceKey": "incoming/web/doc-1/sample.pdf",
        }
    }
    monkeypatch.setattr(app, "table", fake_table)
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"documentId": "doc-1", "deleted": True}

    delete_calls = [call.kwargs for call in fake_s3.delete_object.call_args_list]
    assert {"Bucket": "raw-bucket", "Key": "incoming/web/doc-1/sample.pdf"} in delete_calls
    assert {"Bucket": "processed-bucket", "Key": "canonical/doc-1.json"} in delete_calls
    assert {"Bucket": "processed-bucket", "Key": "xml/doc-1.xml"} in delete_calls
    fake_table.delete_item.assert_called_once_with(Key={"documentId": "doc-1"})


def test_skips_raw_delete_when_source_key_missing(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": {"documentId": "doc-1", "status": "NEEDS_REVIEW"}}
    monkeypatch.setattr(app, "table", fake_table)
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    # Only the two deterministic processed-bucket deletes, no raw delete.
    assert fake_s3.delete_object.call_count == 2
    fake_table.delete_item.assert_called_once_with(Key={"documentId": "doc-1"})
