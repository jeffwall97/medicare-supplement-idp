import io
import json
import os
from unittest.mock import MagicMock

os.environ.setdefault("PROCESSED_BUCKET", "processed-bucket")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("parse_and_validate")

# One answer per default field-map alias, so a fully-answered document
# produces a VALID result (any alias without an answer is treated as
# low-confidence by the handler, regardless of whether it's schema-required).
ANSWERS = {
    "APPLICANT_NAME": "Jane Doe",
    "APPLICANT_DOB": "1950-01-01",
    "MEDICARE_NUMBER": "1EG4-TE5-MK72",
    "PART_A_EFFECTIVE_DATE": "2026-01-01",
    "PART_B_EFFECTIVE_DATE": "2026-01-01",
    "PLAN_SELECTED": "Plan G",
    "PLAN_EFFECTIVE_DATE": "2026-01-01",
    "APPLICANT_ADDRESS": "123 Main St",
    "APPLICANT_PHONE": "555-555-5555",
    "REPLACING_COVERAGE": "No",
    "SIGNATURE_DATE": "2026-01-01",
}


def _blocks_for(answers_with_confidence):
    """answers_with_confidence: {alias: (text, confidence)}"""
    blocks = []
    for i, (alias, (text, confidence)) in enumerate(answers_with_confidence.items()):
        answer_id = f"answer-{i}"
        blocks.append(
            {
                "Id": f"query-{i}",
                "BlockType": "QUERY",
                "Query": {"Alias": alias},
                "Relationships": [{"Type": "ANSWER", "Ids": [answer_id]}],
            }
        )
        blocks.append(
            {
                "Id": answer_id,
                "BlockType": "QUERY_RESULT",
                "Text": text,
                "Confidence": confidence,
            }
        )
    return blocks


def _checkbox_blocks_for(checkboxes):
    """checkboxes: {key_label: (SelectionStatus, confidence)}"""
    blocks = []
    for i, (key_label, (status, confidence)) in enumerate(checkboxes.items()):
        word_id, key_id, value_id, selection_id = (f"word-{i}", f"key-{i}", f"value-{i}", f"selection-{i}")
        blocks.append({"Id": word_id, "BlockType": "WORD", "Text": key_label})
        blocks.append(
            {
                "Id": key_id,
                "BlockType": "KEY_VALUE_SET",
                "EntityTypes": ["KEY"],
                "Relationships": [
                    {"Type": "CHILD", "Ids": [word_id]},
                    {"Type": "VALUE", "Ids": [value_id]},
                ],
            }
        )
        blocks.append(
            {
                "Id": value_id,
                "BlockType": "KEY_VALUE_SET",
                "EntityTypes": ["VALUE"],
                "Relationships": [{"Type": "CHILD", "Ids": [selection_id]}],
            }
        )
        blocks.append(
            {
                "Id": selection_id,
                "BlockType": "SELECTION_ELEMENT",
                "SelectionStatus": status,
                "Confidence": confidence,
            }
        )
    return blocks


def _s3_object(blocks):
    body = MagicMock()
    body.read.return_value = json.dumps({"Blocks": blocks}).encode("utf-8")
    return {"Body": body}


def _event():
    return {
        "document": {"documentId": "doc-1", "bucket": "raw-bucket", "key": "incoming/ca/app.pdf"},
        "classification": {"variant": "DEFAULT", "state": "CA", "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT"},
        "textractStatus": {"resultKey": "textract-output/doc-1.json"},
    }


def test_valid_high_confidence_answers_produce_valid_status(monkeypatch):
    answers = {alias: (text, 99.0) for alias, text in ANSWERS.items()}
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = _s3_object(_blocks_for(answers))
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    assert result["validationStatus"] == "VALID"
    assert result["lowConfidenceFields"] == []
    assert result["schemaErrors"] == []
    assert result["canonicalRecordKey"] == "canonical/doc-1.json"

    saved_kwargs = fake_s3.put_object.call_args.kwargs
    assert saved_kwargs["Bucket"] == "processed-bucket"
    assert saved_kwargs["Key"] == "canonical/doc-1.json"
    saved_record = json.loads(saved_kwargs["Body"])
    assert saved_record["applicantName"] == "Jane Doe"


def test_low_confidence_answer_flags_needs_review(monkeypatch):
    answers = {alias: (text, 99.0) for alias, text in ANSWERS.items()}
    answers["MEDICARE_NUMBER"] = ("1EG4-TE5-MK72", 40.0)
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = _s3_object(_blocks_for(answers))
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    assert result["validationStatus"] == "NEEDS_REVIEW"
    assert "medicareNumber" in result["lowConfidenceFields"]
    assert result["schemaErrors"] == []


def test_missing_required_answer_fails_schema_and_flags_review(monkeypatch):
    answers = {alias: (text, 99.0) for alias, text in ANSWERS.items() if alias != "MEDICARE_NUMBER"}
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = _s3_object(_blocks_for(answers))
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    assert result["validationStatus"] == "NEEDS_REVIEW"
    assert "medicareNumber" in result["lowConfidenceFields"]
    assert any("medicareNumber" in error for error in result["schemaErrors"])


def test_selected_checkbox_fills_in_field_the_query_pass_missed(monkeypatch):
    answers = {alias: (text, 99.0) for alias, text in ANSWERS.items() if alias != "PLAN_SELECTED"}
    checkboxes = {
        "A": ("NOT_SELECTED", 99.0),
        "G": ("SELECTED", 98.5),
        "N": ("NOT_SELECTED", 99.0),
    }
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = _s3_object(_blocks_for(answers) + _checkbox_blocks_for(checkboxes))
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    saved_record = json.loads(fake_s3.put_object.call_args.kwargs["Body"])
    assert saved_record["planSelected"] == "G"
    assert "planSelected" not in result["lowConfidenceFields"]
    assert result["validationStatus"] == "VALID"


def test_high_confidence_checkbox_clears_a_low_confidence_query_answer(monkeypatch):
    answers = {alias: (text, 99.0) for alias, text in ANSWERS.items()}
    answers["REPLACING_COVERAGE"] = ("No", 30.0)
    checkboxes = {"Yes": ("NOT_SELECTED", 99.0), "No": ("SELECTED", 97.0)}
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = _s3_object(_blocks_for(answers) + _checkbox_blocks_for(checkboxes))
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    saved_record = json.loads(fake_s3.put_object.call_args.kwargs["Body"])
    assert saved_record["replacingExistingCoverage"] == "No"
    assert "replacingExistingCoverage" not in result["lowConfidenceFields"]
    assert result["validationStatus"] == "VALID"


def test_no_checkbox_selected_leaves_field_missing_and_flagged(monkeypatch):
    answers = {alias: (text, 99.0) for alias, text in ANSWERS.items() if alias != "PLAN_SELECTED"}
    checkboxes = {"A": ("NOT_SELECTED", 99.0), "G": ("NOT_SELECTED", 99.0)}
    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = _s3_object(_blocks_for(answers) + _checkbox_blocks_for(checkboxes))
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "PROCESSED_BUCKET", "processed-bucket")

    result = app.handler(_event(), None)

    saved_record = json.loads(fake_s3.put_object.call_args.kwargs["Body"])
    assert "planSelected" not in saved_record
    assert "planSelected" in result["lowConfidenceFields"]
    assert result["validationStatus"] == "NEEDS_REVIEW"
