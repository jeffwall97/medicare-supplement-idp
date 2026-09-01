"""PATCH /api/documents/{documentId} -> correct canonical fields on a
NEEDS_REVIEW record.

Only allowed while status is NEEDS_REVIEW: editing a record that hasn't been
flagged (or has already moved past review) isn't a supported flow. Body is a
flat {field: value} object of canonical fields to overwrite; unknown keys are
rejected rather than silently ignored, since a typoed field name would
otherwise disappear without a trace.
"""

import datetime
import json
import os

import boto3
from idp_common.http_responses import json_response
from idp_common.schema import EDITABLE_FIELDS, validate_canonical_record

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def handler(event, context):
    document_id = event["pathParameters"]["documentId"]
    edits = json.loads(event.get("body") or "{}")

    unknown_fields = sorted(set(edits) - EDITABLE_FIELDS)
    if unknown_fields:
        return json_response(400, {"message": f"Unknown or non-editable field(s): {', '.join(unknown_fields)}"})

    result = table.get_item(Key={"documentId": document_id}, ConsistentRead=True)
    item = result.get("Item")
    if not item:
        return json_response(404, {"message": "Document not found"})
    if item.get("status") != "NEEDS_REVIEW":
        return json_response(409, {"message": f"Document status is {item.get('status')}, not NEEDS_REVIEW"})

    canonical_record = dict(item.get("canonicalRecord", {}))
    canonical_record.update(edits)

    schema_errors = validate_canonical_record(canonical_record)
    low_confidence_fields = [field for field in item.get("lowConfidenceFields", []) if field not in edits]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    table.update_item(
        Key={"documentId": document_id},
        UpdateExpression=(
            "SET canonicalRecord = :canonicalRecord, schemaErrors = :schemaErrors, "
            "lowConfidenceFields = :lowConfidenceFields, lastEditedAt = :now"
        ),
        ExpressionAttributeValues={
            ":canonicalRecord": canonical_record,
            ":schemaErrors": schema_errors,
            ":lowConfidenceFields": low_confidence_fields,
            ":now": now,
        },
    )

    item["canonicalRecord"] = canonical_record
    item["schemaErrors"] = schema_errors
    item["lowConfidenceFields"] = low_confidence_fields
    item["lastEditedAt"] = now
    return json_response(200, item)
