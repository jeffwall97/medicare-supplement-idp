"""Kicks off a lightweight OCR pass used only for classification.

Runs before StartTextractAnalysis so classify_document has real document
text to match against idp_common.classification_config, rather than relying
on the S3 upload path/filename. Plain text detection (no FORMS/QUERIES) is
cheaper than the full analysis, and unlike the synchronous Textract APIs it
handles multi-page PDFs and scanned images alike.
"""

import boto3

textract = boto3.client("textract")


def handler(event, context):
    document = event["document"]
    response = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": document["bucket"], "Name": document["key"]}},
    )
    return {"jobId": response["JobId"]}
