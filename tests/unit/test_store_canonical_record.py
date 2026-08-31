import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")
os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("store_canonical_record")


def test_writes_canonical_record_and_metadata_to_dynamodb(monkeypatch):
    canonical_record = {"documentId": "doc-1", "applicantName": "Jane Doe"}
    fake_s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(canonical_record).encode("utf-8")
    fake_s3.get_object.return_value = {"Body": body}
    fake_table = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    event = {
        "document": {"documentId": "doc-1", "bucket": "raw-bucket", "key": "incoming/ca/app.pdf"},
        "classification": {"state": "CA", "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT"},
        "canonical": {
            "canonicalRecordKey": "canonical/doc-1.json",
            "lowConfidenceFields": ["medicareNumber"],
            "schemaErrors": [],
        },
        "status": "NEEDS_REVIEW",
    }

    result = app.handler(event, None)

    assert result == {"documentId": "doc-1", "status": "NEEDS_REVIEW"}
    fake_table.put_item.assert_called_once()
    item = fake_table.put_item.call_args.kwargs["Item"]
    assert item["documentId"] == "doc-1"
    assert item["status"] == "NEEDS_REVIEW"
    assert item["state"] == "CA"
    assert item["canonicalRecord"] == canonical_record
    assert item["lowConfidenceFields"] == ["medicareNumber"]
    assert "ingestedAt" in item
