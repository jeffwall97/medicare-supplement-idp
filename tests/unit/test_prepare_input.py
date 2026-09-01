from unittest.mock import patch

from conftest import load_handler_module

app = load_handler_module("prepare_input")


def _event(key):
    return {
        "detail": {
            "bucket": {"name": "raw-bucket"},
            "object": {"key": key},
        }
    }


def test_extracts_document_id_from_web_upload_key():
    document_id = "11111111-2222-3333-4444-555555555555"
    result = app.handler(_event(f"incoming/web/{document_id}/sample.pdf"), None)

    assert result == {
        "document": {
            "bucket": "raw-bucket",
            "key": f"incoming/web/{document_id}/sample.pdf",
            "documentId": document_id,
        }
    }


def test_non_web_key_falls_back_to_generated_uuid():
    with patch.object(app.uuid, "uuid4", return_value="generated-uuid"):
        result = app.handler(_event("incoming/mi/sample.pdf"), None)

    assert result["document"]["documentId"] == "generated-uuid"


def test_malformed_web_prefix_falls_back_to_generated_uuid():
    with patch.object(app.uuid, "uuid4", return_value="generated-uuid"):
        result = app.handler(_event("incoming/web/not-a-uuid/sample.pdf"), None)

    assert result["document"]["documentId"] == "generated-uuid"
