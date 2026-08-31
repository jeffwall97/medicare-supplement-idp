import json
import os

import boto3

textract = boto3.client("textract")
s3 = boto3.client("s3")
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]


def handler(event, context):
    job_id = event["textractJob"]["jobId"]
    document_id = event["document"]["documentId"]

    status = "IN_PROGRESS"
    blocks = []
    next_token = None

    while True:
        kwargs = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token
        page = textract.get_document_analysis(**kwargs)
        status = page["JobStatus"]
        if status != "SUCCEEDED":
            break
        blocks.extend(page.get("Blocks", []))
        next_token = page.get("NextToken")
        if not next_token:
            break

    if status != "SUCCEEDED":
        return {"jobStatus": status}

    result_key = f"textract-output/{document_id}.json"
    # No explicit ServerSideEncryption here: the bucket's default encryption
    # (SSE-KMS with DocumentsKmsKey) applies automatically. Passing
    # ServerSideEncryption="aws:kms" without a KeyId would instead select the
    # AWS managed key, which our IAM policies don't grant access to.
    s3.put_object(
        Bucket=PROCESSED_BUCKET,
        Key=result_key,
        Body=json.dumps({"Blocks": blocks}).encode("utf-8"),
    )
    return {"jobStatus": status, "resultKey": result_key}
