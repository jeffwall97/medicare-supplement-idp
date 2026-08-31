import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("check_textract_status")


def _event():
    return {
        "document": {"documentId": "doc-1"},
        "textractJob": {"jobId": "job-123"},
    }


def test_returns_status_only_when_job_still_in_progress(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.get_document_analysis.return_value = {"JobStatus": "IN_PROGRESS"}
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "textract", fake_textract)
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event(), None)

    assert result == {"jobStatus": "IN_PROGRESS"}
    fake_s3.put_object.assert_not_called()


def test_writes_merged_blocks_to_s3_when_succeeded_across_pages(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.get_document_analysis.side_effect = [
        {"JobStatus": "SUCCEEDED", "Blocks": [{"Id": "1"}], "NextToken": "next"},
        {"JobStatus": "SUCCEEDED", "Blocks": [{"Id": "2"}]},
    ]
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "textract", fake_textract)
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    assert result == {"jobStatus": "SUCCEEDED", "resultKey": "textract-output/doc-1.json"}
    fake_s3.put_object.assert_called_once()
    call_kwargs = fake_s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "processed-bucket"
    assert call_kwargs["Key"] == "textract-output/doc-1.json"
    saved_blocks = json.loads(call_kwargs["Body"])["Blocks"]
    assert saved_blocks == [{"Id": "1"}, {"Id": "2"}]


def test_returns_status_only_when_job_failed(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.get_document_analysis.return_value = {"JobStatus": "FAILED"}
    fake_s3 = MagicMock()
    monkeypatch.setattr(app, "textract", fake_textract)
    monkeypatch.setattr(app, "s3", fake_s3)

    result = app.handler(_event(), None)

    assert result == {"jobStatus": "FAILED"}
    fake_s3.put_object.assert_not_called()
