"""Configuration-driven document classification.

Each rule identifies a known enrollment form by text markers that reliably
appear on that specific form (carrier name, state, form title) - a
carrier/state combination is onboarded by adding an entry here, the same way
new Textract query sets are onboarded in textract_queries.py. classify_document
matches OCR'd text from a lightweight Textract text-detection pass against
these rules instead of relying on the S3 upload path/filename.

Rules are checked in order; the first whose every marker appears in the
(lowercased) text wins. List more specific rules before more general ones.
"""

CLASSIFICATION_RULES = [
    {
        "variant": "MI",
        "state": "MI",
        "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT",
        "markers": ["blue cross blue shield of michigan", "medicare supplement"],
    },
]

UNKNOWN_STATE = "UNKNOWN"
DEFAULT_VARIANT = "DEFAULT"
DEFAULT_DOCUMENT_TYPE = "MEDICARE_SUPPLEMENT_ENROLLMENT"


def classify_text(text):
    """Match OCR'd document text against CLASSIFICATION_RULES.

    Returns the first matching rule's documentType/state/variant, or an
    UNKNOWN/DEFAULT result if nothing matches (routed to NeedsHumanReview
    downstream via the usual low-confidence/schema-error checks).
    """
    normalized = text.lower()
    for rule in CLASSIFICATION_RULES:
        if all(marker in normalized for marker in rule["markers"]):
            return {
                "documentType": rule["documentType"],
                "state": rule["state"],
                "variant": rule["variant"],
            }
    return {
        "documentType": DEFAULT_DOCUMENT_TYPE,
        "state": UNKNOWN_STATE,
        "variant": DEFAULT_VARIANT,
    }
