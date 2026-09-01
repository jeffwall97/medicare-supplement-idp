import datetime
import json
import os

import boto3

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]


def handler(event, context):
    document = event["document"]
    classification = event["classification"]
    canonical_key = event["canonical"]["canonicalRecordKey"]

    obj = s3.get_object(Bucket=PROCESSED_BUCKET, Key=canonical_key)
    canonical_record = json.loads(obj["Body"].read())

    # UpdateItem, not PutItem: this document's item may already carry an
    # upload-time ingestedAt/originalFilename (from request_upload) or a
    # PROCESSING status (from mark_document_processing) - a PutItem would
    # silently wipe those instead of layering this step's fields on top.
    table.update_item(
        Key={"documentId": document["documentId"]},
        UpdateExpression=(
            "SET #status = :status, #state = :state, documentType = :documentType, "
            "sourceBucket = :sourceBucket, sourceKey = :sourceKey, "
            "ingestedAt = if_not_exists(ingestedAt, :now), "
            "canonicalRecord = :canonicalRecord, "
            "lowConfidenceFields = :lowConfidenceFields, "
            "schemaErrors = :schemaErrors"
        ),
        ExpressionAttributeNames={"#status": "status", "#state": "state"},
        ExpressionAttributeValues={
            ":status": event["status"],
            ":state": classification["state"],
            ":documentType": classification["documentType"],
            ":sourceBucket": document["bucket"],
            ":sourceKey": document["key"],
            ":now": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            ":canonicalRecord": canonical_record,
            ":lowConfidenceFields": event["canonical"].get("lowConfidenceFields", []),
            ":schemaErrors": event["canonical"].get("schemaErrors", []),
        },
    )

    return {"documentId": document["documentId"], "status": event["status"]}
