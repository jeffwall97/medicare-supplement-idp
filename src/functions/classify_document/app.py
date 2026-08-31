"""Determines document type and state/variant so downstream steps know which
Textract query template and field map to use.

v2: matches OCR'd text from the text-detection pass against
idp_common.classification_config.CLASSIFICATION_RULES - a configured set of
per-carrier/state form fingerprints - rather than an S3 upload path
convention. Onboard a new state/carrier by adding a rule there.
"""

from idp_common.classification_config import classify_text


def handler(event, context):
    text = event["textDetection"]["text"]
    return classify_text(text)
