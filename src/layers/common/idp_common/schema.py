import json
import os

from jsonschema import Draft7Validator

CONFIDENCE_THRESHOLD = 75.0

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "canonical_enrollment_schema.json")
with open(_SCHEMA_PATH) as _f:
    _SCHEMA = json.load(_f)

_VALIDATOR = Draft7Validator(_SCHEMA)
REQUIRED_FIELDS = _SCHEMA.get("required", [])

# System-managed fields excluded: not something a human review-edits.
EDITABLE_FIELDS = set(_SCHEMA["properties"]) - {"documentId", "sourceBucket", "sourceKey"}


def validate_canonical_record(record):
    return sorted({error.message for error in _VALIDATOR.iter_errors(record)})
