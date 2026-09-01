"""Shared XML-building and Enrollment API submission logic.

Used by the pipeline's transform_to_xml/submit_enrollment steps and by
resubmit_document (the human-review resubmission path), so the mapping from
canonical record -> XML -> submission result only lives in one place.
"""

import urllib.error
import urllib.request
from xml.sax.saxutils import escape


def build_xml(record):
    """Generic placeholder mapping from the canonical record to XML.

    TODO: replace with the real <InsuranceUpdate> structure/field names used
    by the existing Enrollment API once its XSD or a sample payload is
    available. This currently just serializes canonical field names 1:1.
    """
    fields = "".join(f"<{key}>{escape(str(value))}</{key}>" for key, value in record.items())
    return f'<?xml version="1.0" encoding="UTF-8"?><InsuranceUpdate>{fields}</InsuranceUpdate>'.encode("utf-8")


def submit_to_enrollment_api(xml_body, endpoint):
    """POSTs xml_body to endpoint. Returns (status, error_message).

    status is one of SUBMISSION_SKIPPED (no endpoint configured), SUBMITTED,
    or SUBMISSION_FAILED.
    """
    if not endpoint:
        return "SUBMISSION_SKIPPED", None

    request = urllib.request.Request(
        endpoint,
        data=xml_body,
        headers={"Content-Type": "application/xml"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status >= 300:
                return "SUBMISSION_FAILED", f"Unexpected status code: {response.status}"
    except urllib.error.URLError as exc:
        return "SUBMISSION_FAILED", str(exc)

    return "SUBMITTED", None
