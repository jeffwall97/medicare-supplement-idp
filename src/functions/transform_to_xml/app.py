import json
import os

import boto3
from idp_common import enrollment_submission

s3 = boto3.client("s3")
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]


def handler(event, context):
    document = event["document"]
    canonical_key = event["canonical"]["canonicalRecordKey"]

    obj = s3.get_object(Bucket=PROCESSED_BUCKET, Key=canonical_key)
    canonical_record = json.loads(obj["Body"].read())

    xml_key = f"xml/{document['documentId']}.xml"
    s3.put_object(
        Bucket=PROCESSED_BUCKET,
        Key=xml_key,
        Body=enrollment_submission.build_xml(canonical_record),
    )

    return {"documentId": document["documentId"], "xmlKey": xml_key}
