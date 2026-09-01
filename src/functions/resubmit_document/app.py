"""POST /api/documents/{documentId}/resubmit -> submit a human-reviewed
NEEDS_REVIEW record to the Enrollment API, bypassing the Step Functions
pipeline (no Textract re-run needed - the human already corrected the
extracted fields via PATCH /api/documents/{documentId}).

Builds and submits XML the same way the pipeline's transform_to_xml/
submit_enrollment steps do (idp_common.enrollment_submission), reading the
canonical record straight from DynamoDB rather than the pipeline-run's S3
copy, which the human's edits never touch.
"""

import datetime
import os

import boto3
from idp_common import enrollment_submission
from idp_common.http_responses import json_response
from idp_common.schema import validate_canonical_record

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
ENROLLMENT_API_ENDPOINT = os.environ.get("ENROLLMENT_API_ENDPOINT", "")


def handler(event, context):
    document_id = event["pathParameters"]["documentId"]

    result = table.get_item(Key={"documentId": document_id}, ConsistentRead=True)
    item = result.get("Item")
    if not item:
        return json_response(404, {"message": "Document not found"})
    if item.get("status") != "NEEDS_REVIEW":
        return json_response(409, {"message": f"Document status is {item.get('status')}, not NEEDS_REVIEW"})

    canonical_record = item.get("canonicalRecord", {})
    schema_errors = validate_canonical_record(canonical_record)
    if schema_errors:
        return json_response(422, {"message": "Cannot resubmit: unresolved schema errors", "schemaErrors": schema_errors})

    xml_key = f"xml/{document_id}.xml"
    xml_body = enrollment_submission.build_xml(canonical_record)
    s3.put_object(Bucket=PROCESSED_BUCKET, Key=xml_key, Body=xml_body)

    status, error_message = enrollment_submission.submit_to_enrollment_api(xml_body, ENROLLMENT_API_ENDPOINT)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    update_expression = (
        "SET #status = :status, schemaErrors = :schemaErrors, "
        "lowConfidenceFields = :lowConfidenceFields, resubmittedAt = :now"
    )
    expression_values = {
        ":status": status,
        ":schemaErrors": [],
        ":lowConfidenceFields": [],
        ":now": now,
    }
    if error_message:
        update_expression += ", submissionError = :err"
        expression_values[":err"] = error_message

    table.update_item(
        Key={"documentId": document_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=expression_values,
    )

    item["status"] = status
    item["schemaErrors"] = []
    item["lowConfidenceFields"] = []
    item["resubmittedAt"] = now
    if error_message:
        item["submissionError"] = error_message
    return json_response(200, item)
