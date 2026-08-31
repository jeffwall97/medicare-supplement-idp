import json
import os
import re

import boto3
from idp_common.schema import CONFIDENCE_THRESHOLD, validate_canonical_record
from idp_common.textract_queries import get_field_map_for_variant, get_selection_fields_for_variant

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


def _normalize_label(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _extract_checkbox_answers(blocks):
    """Map normalized FORMS key text to its checkbox's (status, confidence)
    for every key/value pair whose value is a SELECTION_ELEMENT, e.g. a plan
    checkbox row or a yes/no question Textract Queries can't read reliably.
    """
    blocks_by_id = {block["Id"]: block for block in blocks}
    checkboxes = {}
    for block in blocks:
        if block["BlockType"] != "KEY_VALUE_SET" or "KEY" not in block.get("EntityTypes", []):
            continue

        key_words = []
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                key_words = [
                    blocks_by_id[word_id]["Text"]
                    for word_id in relationship["Ids"]
                    if blocks_by_id.get(word_id, {}).get("BlockType") == "WORD"
                ]
            elif relationship["Type"] == "VALUE":
                value_block = blocks_by_id.get(relationship["Ids"][0])
        if not key_words or not value_block:
            continue

        selection_element = None
        for relationship in value_block.get("Relationships", []):
            if relationship["Type"] != "CHILD":
                continue
            for child_id in relationship["Ids"]:
                child = blocks_by_id.get(child_id)
                if child and child["BlockType"] == "SELECTION_ELEMENT":
                    selection_element = child
        if selection_element is None:
            continue

        key_text = _normalize_label(" ".join(key_words))
        checkboxes[key_text] = (
            selection_element.get("SelectionStatus"),
            selection_element.get("Confidence", 0.0),
        )
    return checkboxes


def _find_selected_checkbox(checkboxes, candidate_labels):
    for label in candidate_labels:
        status_and_confidence = checkboxes.get(_normalize_label(label))
        if status_and_confidence and status_and_confidence[0] == "SELECTED":
            return label, status_and_confidence[1]
    return None


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

    # Fields like plan selection or a yes/no question are usually checkboxes
    # on the real form, which Textract Queries doesn't read reliably. For
    # any such field the query pass left missing or low-confidence, check
    # FORMS' checkbox output before giving up on it.
    checkboxes = None
    for canonical_field, candidate_labels in get_selection_fields_for_variant(variant).items():
        if canonical_field in canonical and canonical_field not in low_confidence_fields:
            continue
        if checkboxes is None:
            checkboxes = _extract_checkbox_answers(blocks)
        selected = _find_selected_checkbox(checkboxes, candidate_labels)
        if not selected:
            continue
        label, confidence = selected
        canonical[canonical_field] = label
        if confidence >= CONFIDENCE_THRESHOLD:
            if canonical_field in low_confidence_fields:
                low_confidence_fields.remove(canonical_field)
        elif canonical_field not in low_confidence_fields:
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
