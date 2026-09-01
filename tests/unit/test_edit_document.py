import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("edit_document")


def _event(document_id, edits):
    return {"pathParameters": {"documentId": document_id}, "body": json.dumps(edits)}


def _needs_review_item(**overrides):
    item = {
        "documentId": "doc-1",
        "status": "NEEDS_REVIEW",
        "canonicalRecord": {
            "documentId": "doc-1",
            "applicantName": "Jhn Doe",
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


def test_rejects_unknown_field(monkeypatch):
    fake_table = MagicMock()
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("doc-1", {"notAField": "x"}), None)

    assert result["statusCode"] == 400
    fake_table.get_item.assert_not_called()


def test_returns_404_when_not_found(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("missing-doc", {"applicantName": "Jane Doe"}), None)

    assert result["statusCode"] == 404


def test_returns_409_when_not_needs_review(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item(status="SUBMITTED")}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("doc-1", {"applicantName": "Jane Doe"}), None)

    assert result["statusCode"] == 409
    fake_table.update_item.assert_not_called()


def test_applies_edit_clears_field_from_low_confidence_and_saves(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item()}
    monkeypatch.setattr(app, "table", fake_table)

    result = app.handler(_event("doc-1", {"applicantName": "Jane Doe"}), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["canonicalRecord"]["applicantName"] == "Jane Doe"
    assert body["lowConfidenceFields"] == []
    assert body["schemaErrors"] == []

    update_kwargs = fake_table.update_item.call_args.kwargs
    values = update_kwargs["ExpressionAttributeValues"]
    assert values[":canonicalRecord"]["applicantName"] == "Jane Doe"
    assert values[":lowConfidenceFields"] == []
    assert values[":schemaErrors"] == []


def test_edit_with_wrong_type_surfaces_schema_error(monkeypatch):
    fake_table = MagicMock()
    fake_table.get_item.return_value = {"Item": _needs_review_item()}
    monkeypatch.setattr(app, "table", fake_table)

    # medicareNumber must be a string per the canonical schema - confirms
    # validate_canonical_record runs against the merged record, not the
    # stale one, and that a bad edit is surfaced rather than silently saved.
    result = app.handler(_event("doc-1", {"medicareNumber": 12345}), None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["schemaErrors"]
