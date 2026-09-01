"""Issues a presigned S3 upload URL and creates the initial tracking record.

POST /api/documents  {"filename": "..."}
-> 201 {"documentId", "uploadUrl", "bucket", "key", "expiresIn"}

The browser then PUTs the file directly to uploadUrl (never through this
Lambda/API Gateway, avoiding their payload-size limits). generate_presigned_url
is a local signing call - it succeeds even without S3 permissions, but the
browser's actual PUT is authorized against this function's own role at
upload time, so it needs real s3:PutObject + kms:GenerateDataKey grants (see
template.yaml) or the upload will fail with a 403 despite a "successful"
response here.
"""

import datetime
import json
import os
import re
import uuid

import boto3
from botocore.client import Config
from idp_common.http_responses import json_response

# S3 requires SigV4 for requests against an SSE-KMS bucket, but boto3
# defaults to the legacy SigV2 presigned-URL signer in us-east-1 unless
# told otherwise - without this, uploads fail with "Requests specifying
# Server Side Encryption with AWS KMS managed keys require AWS Signature
# Version 4."
s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
RAW_BUCKET = os.environ["RAW_BUCKET"]
UPLOAD_URL_EXPIRES_IN = 900

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(filename):
    name = os.path.basename(filename or "document.pdf")
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)[:200]
    return name or "document.pdf"


def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    filename = _sanitize_filename(body.get("filename"))

    document_id = str(uuid.uuid4())
    key = f"incoming/web/{document_id}/{filename}"

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": RAW_BUCKET, "Key": key},
        ExpiresIn=UPLOAD_URL_EXPIRES_IN,
    )

    table.put_item(
        Item={
            "documentId": document_id,
            "status": "UPLOADED",
            "ingestedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sourceBucket": RAW_BUCKET,
            "sourceKey": key,
            "originalFilename": filename,
        }
    )

    return json_response(
        201,
        {
            "documentId": document_id,
            "uploadUrl": upload_url,
            "bucket": RAW_BUCKET,
            "key": key,
            "expiresIn": UPLOAD_URL_EXPIRES_IN,
        },
    )
