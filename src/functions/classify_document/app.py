"""Determines document type and state/variant so downstream steps know which
Textract query template and field map to use.

v1 relies on an "incoming/<state>/<filename>" upload convention. Replace with
real content-based classification (Textract + keyword matching, or Comprehend)
once documents arrive without a reliable folder/filename convention.
"""


def handler(event, context):
    document = event["document"]
    key_parts = document["key"].split("/")

    state = "UNKNOWN"
    if len(key_parts) > 2 and key_parts[0] == "incoming":
        state = key_parts[1].upper()

    return {
        "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT",
        "state": state,
        "variant": state if state != "UNKNOWN" else "DEFAULT",
    }
