"""GET /api/documents/{documentId}/view -> 302 redirect to a short-lived
presigned S3 GET URL for the originally uploaded PDF.

A plain <a target="_blank" href="/api/documents/{id}/view"> link can point
straight at this route: the browser's top-level navigation follows the
redirect directly to S3 (a different origin than CloudFront, same as the
presigned PUT the upload flow already uses) rather than proxying PDF bytes
through API Gateway/Lambda, and CORS doesn't apply to that kind of
navigation at all - only to same-page fetch/XHR.
"""

import os

import boto3
from botocore.client import Config
from idp_common.http_responses import json_response

# S3 requires SigV4 for requests against an SSE-KMS bucket, but boto3
# defaults to the legacy SigV2 presigned-URL signer in us-east-1 unless
# told otherwise - same lesson as request_upload's presigned PUT URL.
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
VIEW_URL_EXPIRES_IN = 300


def handler(event, context):
    document_id = event["pathParameters"]["documentId"]

    result = table.get_item(Key={"documentId": document_id}, ConsistentRead=True)
    item = result.get("Item")
    if not item or not item.get("sourceBucket") or not item.get("sourceKey"):
        return json_response(404, {"message": "Document not found"})

    view_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": item["sourceBucket"],
            "Key": item["sourceKey"],
            # Forces inline PDF-viewer rendering in the new tab rather than
            # a download, regardless of what Content-Type the browser sent
            # on the original upload PUT.
            "ResponseContentType": "application/pdf",
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=VIEW_URL_EXPIRES_IN,
    )

    return {"statusCode": 302, "headers": {"Location": view_url}}
