import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")
os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("resubmit_document")


def _event(document_id):
    return {"pathParameters": {"documentId": document_id}}


def _needs_review_item(**overrides):
    item = {
        "documentId": "doc-1",
        "status": "NEEDS_REVIEW",
        "canonicalRecord": {
            "documentId": "doc-1",
            "applicantName": "Jane Doe",
            "applicantDateOfBirth": "01/01/1950",
            "medicareNumber": "1EG4-TE5-MK72",
            "planSelected": "Plan G",
            "planEffectiveDate": "01/01/2026",
        },
        "lowConfidenceFields": ["applicantName"],
        "schemaErrors": [],
    }
    item.update(overrides)
    return item


def test_returns_404_when_not_found(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("missing-doc"), None)

    assert result["statusCode"] == 404


def test_returns_409_when_not_needs_review(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item(status="SUBMITTED")}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 409


def test_returns_422_when_schema_errors_remain(monkeypatch):
    incomplete_record = {"documentId": "doc-1"}  # missing required fields
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item(canonicalRecord=incomplete_record)}
    monkeypatch.setattr(app, "table", fake_table)
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 422
    body = json.loads(result["body"])
    assert body["schemaErrors"]
    fake_s3.put_object.assert_not_called()
    fake_table.update_item.assert_not_called()


def test_skips_submission_when_no_endpoint_configured(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item()}
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "s3", MagicMock())
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "")

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "SUBMISSION_SKIPPED"
    assert body["lowConfidenceFields"] == []

    update_kwargs = fake_table.update_item.call_args.kwargs
    assert update_kwargs["ExpressionAttributeValues"][":status"] == "SUBMISSION_SKIPPED"
    assert update_kwargs["ExpressionAttributeValues"][":lowConfidenceFields"] == []


def test_marks_submitted_on_successful_post(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item()}
    monkeypatch.setattr(app, "table", fake_table)
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "https://enrollment.example.com/insurance-update")

    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.__enter__.return_value = fake_response
    monkeypatch.setattr(app.enrollment_submission.urllib.request, "urlopen", MagicMock(return_value=fake_response))

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "SUBMITTED"

    put_kwargs = fake_s3.put_object.call_args.kwargs
    assert put_kwargs["Bucket"] == "processed-bucket"
    assert put_kwargs["Key"] == "xml/doc-1.xml"
    assert b"<applicantName>Jane Doe</applicantName>" in put_kwargs["Body"]


def test_marks_failed_on_connection_error(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item()}
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "s3", MagicMock())
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "https://enrollment.example.com/insurance-update")

    import urllib.error

    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(app.enrollment_submission.urllib.request, "urlopen", raise_url_error)

    result = app.handler(_event("doc-1"), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "SUBMISSION_FAILED"
    assert "connection refused" in body["submissionError"]
