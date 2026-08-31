from unittest.mock import MagicMock

from conftest import load_handler_module

app = load_handler_module("start_textract_analysis")


def test_starts_analysis_with_default_queries_and_returns_job_id(monkeypatch):
    fake_textract = MagicMock()
    fake_textract.start_document_analysis.return_value = {"JobId": "job-123"}
    monkeypatch.setattr(app, "textract", fake_textract)

    event = {
        "document": {"bucket": "raw-bucket", "key": "incoming/ca/app.pdf", "documentId": "doc-1"},
        "classification": {"variant": "DEFAULT"},
    }

    result = app.handler(event, None)

    assert result == {"jobId": "job-123"}
    fake_textract.start_document_analysis.assert_called_once()
    call_kwargs = fake_textract.start_document_analysis.call_args.kwargs
    assert call_kwargs["DocumentLocation"] == {
        "S3Object": {"Bucket": "raw-bucket", "Name": "incoming/ca/app.pdf"}
    }
    assert call_kwargs["FeatureTypes"] == ["FORMS", "QUERIES"]
    assert len(call_kwargs["QueriesConfig"]["Queries"]) > 0
