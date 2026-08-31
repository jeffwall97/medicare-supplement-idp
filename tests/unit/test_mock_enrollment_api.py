import base64
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "mock-enrollment-submissions")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("mock_enrollment_api")

SAMPLE_XML = '<?xml version="1.0" encoding="UTF-8"?><InsuranceUpdate><documentId>doc-1</documentId></InsuranceUpdate>'


def test_accepts_valid_submission_and_stores_it(monkeypatch):
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"body": SAMPLE_XML, "isBase64Encoded": False}, None)

    assert result["statusCode"] == 200
    assert "<status>ACCEPTED</status>" in result["body"]
    assert "<confirmationNumber>" in result["body"]

    item = fake_table.put_item.call_args.kwargs["Item"]
    assert item["documentId"] == "doc-1"
    assert item["rawXml"] == SAMPLE_XML
    assert "submissionId" in item
    assert "receivedAt" in item


def test_decodes_base64_encoded_body(monkeypatch):
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)
    encoded_body = base64.b64encode(SAMPLE_XML.encode("utf-8")).decode("ascii")

    result = app.handler({"body": encoded_body, "isBase64Encoded": True}, None)

    assert result["statusCode"] == 200
    item = fake_table.put_item.call_args.kwargs["Item"]
    assert item["rawXml"] == SAMPLE_XML


def test_rejects_empty_body(monkeypatch):
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"body": "", "isBase64Encoded": False}, None)

    assert result["statusCode"] == 400
    assert "<status>REJECTED</status>" in result["body"]
    fake_table.put_item.assert_not_called()


def test_missing_document_id_defaults_to_unknown(monkeypatch):
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler({"body": "<InsuranceUpdate><foo>bar</foo></InsuranceUpdate>"}, None)

    assert result["statusCode"] == 200
    item = fake_table.put_item.call_args.kwargs["Item"]
    assert item["documentId"] == "UNKNOWN"
