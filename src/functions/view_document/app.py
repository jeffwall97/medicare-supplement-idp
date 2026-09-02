"""GET /api/documents/{documentId}/view -> {"viewUrl": <short-lived presigned
S3 GET URL>} for the originally uploaded PDF.

Returns the URL as JSON rather than a 302 redirect: this route sits behind
WebAppApi's Cognito authorizer, so the frontend must call it with fetch (an
Authorization header can't ride along on a plain <a> navigation) - and a
fetch that *follows* a cross-origin redirect needs the final response (S3)
to carry CORS headers too, which RawDocumentsBucket's CORS policy doesn't
grant for GET. Handing back the URL as data instead sidesteps that: the
frontend does a plain top-level navigation to it (new tab), which - like
the presigned PUT the upload flow already uses - isn't a CORS-checked
request at all.
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

    return json_response(200, {"viewUrl": view_url})
