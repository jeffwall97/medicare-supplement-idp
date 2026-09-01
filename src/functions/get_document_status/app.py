"""GET /api/documents/{documentId} -> the tracking record, or 404."""

import os

import boto3
from idp_common.http_responses import json_response

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def handler(event, context):
    document_id = event["pathParameters"]["documentId"]

    result = table.get_item(Key={"documentId": document_id}, ConsistentRead=True)
    item = result.get("Item")

    if not item:
        return json_response(404, {"message": "Document not found"})

    return json_response(200, item)
