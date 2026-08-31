from idp_common.schema import CONFIDENCE_THRESHOLD, REQUIRED_FIELDS, validate_canonical_record

VALID_RECORD = {
    "documentId": "doc-123",
    "state": "CA",
    "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT",
    "applicantName": "Jane Doe",
    "applicantDateOfBirth": "1950-01-01",
    "medicareNumber": "1EG4-TE5-MK72",
    "planSelected": "Plan G",
    "planEffectiveDate": "2026-01-01",
}


def test_valid_record_has_no_errors():
    assert validate_canonical_record(VALID_RECORD) == []


def test_missing_required_field_is_reported():
    record = {k: v for k, v in VALID_RECORD.items() if k != "medicareNumber"}
    errors = validate_canonical_record(record)
    assert any("medicareNumber" in error for error in errors)


def test_wrong_type_is_reported():
    record = {**VALID_RECORD, "applicantName": 12345}
    errors = validate_canonical_record(record)
    assert len(errors) == 1
    assert "12345" in errors[0]


def test_required_fields_matches_schema():
    assert set(REQUIRED_FIELDS) == {
        "documentId",
        "applicantName",
        "applicantDateOfBirth",
        "medicareNumber",
        "planSelected",
        "planEffectiveDate",
    }


def test_confidence_threshold_is_a_percentage():
    assert 0 < CONFIDENCE_THRESHOLD <= 100
