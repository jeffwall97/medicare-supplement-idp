"""Records that a document has been classified and is now processing.

Runs right after ClassifyDocument. Uses if_not_exists so it never clobbers
the ingestedAt timestamp an upload-time record (from request_upload) already
set, but still creates a first record for documents that entered the
pipeline outside the web app (e.g. the CLI incoming/<state>/ convention).
"""

import datetime
import os

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def handler(event, context):
    document = event["document"]
    classification = event["classification"]

    table.update_item(
        Key={"documentId": document["documentId"]},
        UpdateExpression=(
            "SET #status = :status, #state = :state, documentType = :documentType, "
            "sourceBucket = :sourceBucket, sourceKey = :sourceKey, "
            "ingestedAt = if_not_exists(ingestedAt, :now)"
        ),
        ExpressionAttributeNames={"#status": "status", "#state": "state"},
        ExpressionAttributeValues={
            ":status": "PROCESSING",
            ":state": classification["state"],
            ":documentType": classification["documentType"],
            ":sourceBucket": document["bucket"],
            ":sourceKey": document["key"],
            ":now": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    )

    return {"documentId": document["documentId"], "status": "PROCESSING"}
