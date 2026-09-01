"""Normalizes the EventBridge S3 event into the pipeline's document shape.

If the object was uploaded through the web app's request_upload API, its key
follows incoming/web/<documentId>/<filename> - extract that documentId so
the web app's tracking record (created at upload time) and the pipeline's
own writes land on the same DynamoDB item. Any other key (e.g. the CLI
incoming/<state>/<filename> convention) gets a freshly generated documentId,
exactly as before this function existed.
"""

import re
import uuid

WEB_UPLOAD_KEY_PATTERN = re.compile(r"^incoming/web/(?P<document_id>[0-9a-fA-F-]{36})/")


def handler(event, context):
    bucket = event["detail"]["bucket"]["name"]
    key = event["detail"]["object"]["key"]

    match = WEB_UPLOAD_KEY_PATTERN.match(key)
    document_id = match.group("document_id") if match else str(uuid.uuid4())

    return {"document": {"bucket": bucket, "key": key, "documentId": document_id}}
