"""Polls the classification text-detection job and returns its text.

The extracted text is small (a page or two of LINE text, well under Step
Functions' state size limit) so it's returned directly rather than written
to S3 like the full Textract analysis output.
"""

import boto3

textract = boto3.client("textract")


def handler(event, context):
    job_id = event["textDetectionJob"]["jobId"]

    status = "IN_PROGRESS"
    lines = []
    next_token = None

    while True:
        kwargs = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token
        page = textract.get_document_text_detection(**kwargs)
        status = page["JobStatus"]
        if status != "SUCCEEDED":
            break
        lines.extend(block["Text"] for block in page.get("Blocks", []) if block["BlockType"] == "LINE")
        next_token = page.get("NextToken")
        if not next_token:
            break

    if status != "SUCCEEDED":
        return {"jobStatus": status}

    return {"jobStatus": status, "text": "\n".join(lines)}
