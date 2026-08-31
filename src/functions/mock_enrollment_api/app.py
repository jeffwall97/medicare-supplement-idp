"""Stand-in for the real Enrollment API's "insurance update" endpoint.

Accepts the <InsuranceUpdate> XML posted by submit_enrollment, stores it
so submissions can be inspected during development/testing, and returns an
acknowledgement. Dev/test only - see the DeployMockEnrollmentApi condition
in template.yaml (never deployed for Stage=prod). No authentication.
"""

import base64
import datetime
import os
import uuid
import xml.etree.ElementTree as ET

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _decode_body(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return body


def _extract_document_id(xml_body):
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError:
        return None
    element = root.find("documentId")
    return element.text if element is not None else None


def _xml_response(status_code, status, extra=""):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/xml"},
        "body": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<InsuranceUpdateAck><status>{status}</status>{extra}</InsuranceUpdateAck>"
        ),
    }


def handler(event, context):
    xml_body = _decode_body(event)

    if not xml_body.strip():
        return _xml_response(400, "REJECTED", "<reason>Empty request body</reason>")

    submission_id = str(uuid.uuid4())
    table.put_item(
        Item={
            "submissionId": submission_id,
            "receivedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "documentId": _extract_document_id(xml_body) or "UNKNOWN",
            "rawXml": xml_body,
        }
    )

    return _xml_response(200, "ACCEPTED", f"<confirmationNumber>{submission_id}</confirmationNumber>")
