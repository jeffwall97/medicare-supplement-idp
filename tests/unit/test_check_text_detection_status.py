from unittest.mock import MagicMock

from conftest import load_handler_module

app = load_handler_module("check_text_detection_status")


def _event():
    return {"textDetectionJob": {"jobId": "job-456"}}


def test_returns_status_only_when_job_still_in_progress(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.get_document_text_detection.return_value = {"JobStatus": "IN_PROGRESS"}
    monkeypatch.setattr(app, "textract", fake_textract)

    result = app.handler(_event(), None)

    assert result == {"jobStatus": "IN_PROGRESS"}


def test_joins_line_blocks_across_pages_into_text(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.get_document_text_detection.side_effect = [
        {
            "JobStatus": "SUCCEEDED",
            "Blocks": [
                {"BlockType": "LINE", "Text": "Blue Cross Medicare Supplement"},
                {"BlockType": "WORD", "Text": "ignored"},
            ],
            "NextToken": "next",
        },
        {
            "JobStatus": "SUCCEEDED",
            "Blocks": [{"BlockType": "LINE", "Text": "Blue Cross Blue Shield of Michigan"}],
        },
    ]
    monkeypatch.setattr(app, "textract", fake_textract)

    result = app.handler(_event(), None)

    assert result == {
        "jobStatus": "SUCCEEDED",
        "text": "Blue Cross Medicare Supplement\nBlue Cross Blue Shield of Michigan",
    }


def test_returns_status_only_when_job_failed(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.get_document_text_detection.return_value = {"JobStatus": "FAILED"}
    monkeypatch.setattr(app, "textract", fake_textract)

    result = app.handler(_event(), None)

    assert result == {"jobStatus": "FAILED"}
