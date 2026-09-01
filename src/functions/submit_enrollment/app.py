import os

import boto3
from idp_common import enrollment_submission

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
PROCESSED_BUCKET = os.environ["PROCESSED_BUCKET"]
ENROLLMENT_API_ENDPOINT = os.environ.get("ENROLLMENT_API_ENDPOINT", "")


def handler(event, context):
    """Posts the transformed XML to the existing Enrollment API.

    TODO: add real authentication (API key / OAuth / mTLS - whatever the
    Enrollment API requires) once confirmed; likely pulled from Secrets
    Manager rather than an env var.
    """
    document_id = event["document"]["documentId"]
    xml_key = event["xmlPayload"]["xmlKey"]

    obj = s3.get_object(Bucket=PROCESSED_BUCKET, Key=xml_key)
    xml_body = obj["Body"].read()

    status, error_message = enrollment_submission.submit_to_enrollment_api(xml_body, ENROLLMENT_API_ENDPOINT)

    update_expression = "SET #status = :status"
    expression_names = {"#status": "status"}
    expression_values = {":status": status}
    if error_message:
        update_expression += ", submissionError = :err"
        expression_values[":err"] = error_message

    table.update_item(
        Key={"documentId": document_id},
        UpdateExpression=update_expression,
        ExpressionAttributeNames=expression_names,
        ExpressionAttributeValues=expression_values,
    )

    return {"documentId": document_id, "status": status}
