import os
import urllib.error
from unittest.mock import MagicMock

os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")
os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("submit_enrollment")


def _event():
    return {
        "document": {"documentId": "doc-1"},
        "xmlPayload": {"xmlKey": "xml/doc-1.xml"},
    }


def _mock_s3(monkeypatch):
    fake_s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = b"<InsuranceUpdate/>"
    fake_s3.get_object.return_value = {"Body": body}
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")
    return fake_s3


def test_skips_submission_when_no_endpoint_configured(monkeypatch):
    _mock_s3(monkeypatch)
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "")

    result = app.handler(_event(), None)

    assert result == {"documentId": "doc-1", "status": "SUBMISSION_SKIPPED"}
    update_kwargs = fake_table.update_item.call_args.kwargs
    assert update_kwargs["ExpressionAttributeValues"][":status"] == "SUBMISSION_SKIPPED"
    assert "submissionError = :err" not in update_kwargs["UpdateExpression"]


def test_marks_submitted_on_successful_post(monkeypatch):
    _mock_s3(monkeypatch)
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "https://enrollment.example.com/insurance-update")

    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.__enter__.return_value = fake_response
    monkeypatch.setattr(app.enrollment_submission.urllib.request, "urlopen", MagicMock(return_value=fake_response))

    result = app.handler(_event(), None)

    assert result == {"documentId": "doc-1", "status": "SUBMITTED"}
    update_kwargs = fake_table.update_item.call_args.kwargs
    assert update_kwargs["ExpressionAttributeValues"][":status"] == "SUBMITTED"


def test_marks_failed_on_non_2xx_response(monkeypatch):
    _mock_s3(monkeypatch)
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "https://enrollment.example.com/insurance-update")

    fake_response = MagicMock()
    fake_response.status = 500
    fake_response.__enter__.return_value = fake_response
    monkeypatch.setattr(app.enrollment_submission.urllib.request, "urlopen", MagicMock(return_value=fake_response))

    result = app.handler(_event(), None)

    assert result == {"documentId": "doc-1", "status": "SUBMISSION_FAILED"}
    update_kwargs = fake_table.update_item.call_args.kwargs
    assert update_kwargs["ExpressionAttributeValues"][":status"] == "SUBMISSION_FAILED"
    assert "Unexpected status code: 500" in update_kwargs["ExpressionAttributeValues"][":err"]


def test_marks_failed_on_connection_error(monkeypatch):
    _mock_s3(monkeypatch)
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "ENROLLMENT_API_ENDPOINT", "https://enrollment.example.com/insurance-update")

    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(app.enrollment_submission.urllib.request, "urlopen", raise_url_error)

    result = app.handler(_event(), None)

    assert result == {"documentId": "doc-1", "status": "SUBMISSION_FAILED"}
    update_kwargs = fake_table.update_item.call_args.kwargs
    assert "connection refused" in update_kwargs["ExpressionAttributeValues"][":err"]
