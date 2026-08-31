import boto3
from idp_common.textract_queries import get_queries_for_variant

textract = boto3.client("textract")


def handler(event, context):
    document = event["document"]
    variant = event["classification"]["variant"]
    queries = get_queries_for_variant(variant)

    response = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": document["bucket"], "Name": document["key"]}},
        FeatureTypes=["FORMS", "QUERIES"],
        QueriesConfig={"Queries": queries},
    )
    return {"jobId": response["JobId"]}
