from unittest.mock import MagicMock

from conftest import load_handler_module

app = load_handler_module("start_text_detection")


def test_starts_text_detection_and_returns_job_id(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.start_document_text_detection.return_value = {"JobId": "job-456"}
    monkeypatch.setattr(app, "textract", fake_textract)

    event = {"document": {"bucket": "raw-bucket", "key": "incoming/mi/app.pdf", "documentId": "doc-1"}}

    result = app.handler(event, None)

    assert result == {"jobId": "job-456"}
    fake_textract.start_document_text_detection.assert_called_once_with(
        DocumentLocation={"S3Object": {"Bucket": "raw-bucket", "Name": "incoming/mi/app.pdf"}}
    )
