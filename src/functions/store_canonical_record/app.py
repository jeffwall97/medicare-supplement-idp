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

    table.put_item(
        Item={
            "documentId": document["documentId"],
            "status": event["status"],
            "state": classification["state"],
            "documentType": classification["documentType"],
            "ingestedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sourceBucket": document["bucket"],
            "sourceKey": document["key"],
            "canonicalRecord": canonical_record,
            "lowConfidenceFields": event["canonical"].get("lowConfidenceFields", []),
            "schemaErrors": event["canonical"].get("schemaErrors", []),
        }
    )

    return {"documentId": document["documentId"], "status": event["status"]}
