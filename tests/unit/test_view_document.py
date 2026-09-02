import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("view_document")


def _event(document_id):
    return {"pathParameters": {"documentId": document_id}}


def test_returns_404_when_not_found(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("missing-doc"), None)

    assert result["statusCode"] == 404


def test_returns_404_when_no_source_key(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": {"documentId": "doc-1", "status": "UPLOADED"}}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 404


def test_returns_presigned_url_as_json(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {
        "Item": {
            "documentId": "doc-1",
            "sourceBucket": "raw-bucket",
            "sourceKey": "incoming/web/doc-1/sample.pdf",
        }
    }
    monkeypatch.setattr(app, "table", fake_table)
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url.return_value = "https://raw-bucket.s3.amazonaws.com/signed-url"
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"viewUrl": "https://raw-bucket.s3.amazonaws.com/signed-url"}

    call_kwargs = fake_s3.generate_presigned_url.call_args
    assert call_kwargs.args[0] == "get_object"
    params = call_kwargs.kwargs["Params"]
    assert params["Bucket"] == "raw-bucket"
    assert params["Key"] == "incoming/web/doc-1/sample.pdf"
    assert params["ResponseContentType"] == "application/pdf"
    assert params["ResponseContentDisposition"] == "inline"
