import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("transform_to_xml")


def test_writes_xml_with_escaped_field_values(monkeypatch):
    canonical_record = {"applicantName": "Jane & Doe <Jr>", "medicareNumber": "1EG4-TE5-MK72"}
    fake_s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(canonical_record).encode("utf-8")
    fake_s3.get_object.return_value = {"Body": body}
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    event = {
        "document": {"documentId": "doc-1"},
        "canonical": {"canonicalRecordKey": "canonical/doc-1.json"},
    }

    result = app.handler(event, None)

    assert result == {"documentId": "doc-1", "xmlKey": "xml/doc-1.xml"}
    call_kwargs = fake_s3.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "processed-bucket"
    assert call_kwargs["Key"] == "xml/doc-1.xml"
    xml_body = call_kwargs["Body"].decode("utf-8")
    assert xml_body.startswith('<?xml version="1.0" encoding="UTF-8"?><InsuranceUpdate>')
    assert "<applicantName>Jane &amp; Doe &lt;Jr&gt;</applicantName>" in xml_body
    assert "<medicareNumber>1EG4-TE5-MK72</medicareNumber>" in xml_body
