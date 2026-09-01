"""DELETE /api/documents/{documentId} -> permanently delete a document's
tracking record and its underlying S3 objects (raw upload, plus any
processed canonical/xml output).

Blocked while the pipeline may still be actively writing to the record
(UPLOADED/PROCESSING): mark_document_processing/store_canonical_record write
via UpdateItem with if_not_exists(), which creates the item fresh if it's
gone - deleting mid-flight would race with those and could "resurrect" a
partial record right after the delete appeared to succeed.
"""

import os

import boto3
from idp_common.http_responses import json_response

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]

BLOCKED_STATUSES = {"UPLOADED", "PROCESSING"}


def handler(event, context):
    document_id = event["pathParameters"]["documentId"]

    result = table.get_item(Key={"documentId": document_id}, ConsistentRead=True)
    item = result.get("Item")
    if not item:
        return json_response(404, {"message": "Document not found"})
    if item.get("status") in BLOCKED_STATUSES:
        return json_response(409, {"message": f"Cannot delete a document while it is {item.get('status')}"})

    source_bucket = item.get("sourceBucket")
    source_key = item.get("sourceKey")
    if source_bucket and source_key:
        s3.delete_object(Bucket=source_bucket, Key=source_key)

    # canonical/xml keys are deterministic (documentId-based) - delete_object
    # is a no-op if a given one was never written (e.g. the document never
    # reached parse_and_validate, so no canonical JSON exists).
    s3.delete_object(Bucket=PROCESSED_BUCKET, Key=f"canonical/{document_id}.json")
    s3.delete_object(Bucket=PROCESSED_BUCKET, Key=f"xml/{document_id}.xml")

    table.delete_item(Key={"documentId": document_id})

    return json_response(200, {"documentId": document_id, "deleted": True})
