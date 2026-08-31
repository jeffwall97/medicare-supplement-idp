import json
import os

import boto3
from idp_common.schema import CONFIDENCE_THRESHOLD, validate_canonical_record
from idp_common.textract_queries import get_field_map_for_variant

s3 = boto3.client("s3")
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]


def _extract_query_answers(blocks):
    blocks_by_id = {block["Id"]: block for block in blocks}
    answers = {}
    for block in blocks:
        if block["BlockType"] != "QUERY":
            continue
        alias = block["Query"]["Alias"]
        for relationship in block.get("Relationships", []):
            if relationship["Type"] != "ANSWER":
                continue
            answer_block = blocks_by_id.get(relationship["Ids"][0])
            if answer_block:
                answers[alias] = {
                    "text": answer_block.get("Text", ""),
                    "confidence": answer_block.get("Confidence", 0.0),
                }
            break
    return answers


def handler(event, context):
    document = event["document"]
    classification = event["classification"]
    variant = classification["variant"]

    textract_output = s3.get_object(Bucket=PROCESSED_BUCKET, Key=event["textractStatus"]["resultKey"])
    blocks = json.loads(textract_output["Body"].read())["Blocks"]
    answers = _extract_query_answers(blocks)
    field_map = get_field_map_for_variant(variant)

    canonical = {
        "documentId": document["documentId"],
        "state": classification["state"],
        "documentType": classification["documentType"],
        "sourceBucket": document["bucket"],
        "sourceKey": document["key"],
    }

    low_confidence_fields = []
    for alias, canonical_field in field_map.items():
        answer = answers.get(alias)
        if not answer:
            low_confidence_fields.append(canonical_field)
            continue
        canonical[canonical_field] = answer["text"]
        if answer["confidence"] < CONFIDENCE_THRESHOLD:
            low_confidence_fields.append(canonical_field)

    schema_errors = validate_canonical_record(canonical)
    validation_status = "VALID" if not schema_errors and not low_confidence_fields else "NEEDS_REVIEW"

    canonical_key = f"canonical/{document['documentId']}.json"
    s3.put_object(
        Bucket=PROCESSED_BUCKET,
        Key=canonical_key,
        Body=json.dumps(canonical).encode("utf-8"),
    )

    return {
        "documentId": document["documentId"],
        "canonicalRecordKey": canonical_key,
        "validationStatus": validation_status,
        "lowConfidenceFields": low_confidence_fields,
        "schemaErrors": schema_errors,
    }
