import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("mark_document_processing")


def test_updates_status_to_processing(monkeypatch):
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)

    event = {
        "document": {"documentId": "doc-1", "bucket": "raw-bucket", "key": "incoming/web/doc-1/app.pdf"},
        "classification": {"state": "MI", "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT", "variant": "MI"},
    }

    result = app.handler(event, None)

    assert result == {"documentId": "doc-1", "status": "PROCESSING"}
    call_kwargs = fake_table.update_item.call_args.kwargs
    assert call_kwargs["Key"] == {"documentId": "doc-1"}
    values = call_kwargs["ExpressionAttributeValues"]
    assert values[":status"] == "PROCESSING"
    assert values[":state"] == "MI"
    assert values[":documentType"] == "MEDICARE_SUPPLEMENT_ENROLLMENT"
    assert values[":sourceBucket"] == "raw-bucket"
    assert values[":sourceKey"] == "incoming/web/doc-1/app.pdf"
    assert "if_not_exists(ingestedAt, :now)" in call_kwargs["UpdateExpression"]
