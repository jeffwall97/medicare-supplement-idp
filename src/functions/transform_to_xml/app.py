import json
import os
from xml.sax.saxutils import escape

import boto3

s3 = boto3.client("s3")
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]


def _build_xml(record):
    """Generic placeholder mapping from the canonical record to XML.

    TODO: replace with the real <InsuranceUpdate> structure/field names used
    by the existing Enrollment API once its XSD or a sample payload is
    available. This currently just serializes canonical field names 1:1.
    """
    fields = "".join(f"<{key}>{escape(str(value))}</{key}>" for key, value in record.items())
    return f'<?xml version="1.0" encoding="UTF-8"?><InsuranceUpdate>{fields}</InsuranceUpdate>'


def handler(event, context):
    document = event["document"]
    canonical_key = event["canonical"]["canonicalRecordKey"]

    obj = s3.get_object(Bucket=PROCESSED_BUCKET, Key=canonical_key)
    canonical_record = json.loads(obj["Body"].read())

    xml_key = f"xml/{document['documentId']}.xml"
    s3.put_object(
        Bucket=PROCESSED_BUCKET,
        Key=xml_key,
        Body=_build_xml(canonical_record).encode("utf-8"),
    )

    return {"documentId": document["documentId"], "xmlKey": xml_key}
