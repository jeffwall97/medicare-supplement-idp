"""GET /api/documents?limit= -> recent documents, newest first.

A single Scan (DynamoDB caps each response at 1MB, comfortably enough items
for this project's dev/demo scale) sorted by ingestedAt in Python, since a
Scan's own Limit stops after examining N items in arbitrary order rather
than returning the N most recent. If this ever needs to handle real volume,
replace with a GSI keyed on a constant partition + ingestedAt sort key
instead of scaling this up.
"""

import os

import boto3
from idp_common.http_responses import json_response

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def _parse_limit(query_params):
    raw = (query_params or {}).get("limit")
    if not raw:
        return DEFAULT_LIMIT
    try:
        return max(1, min(MAX_LIMIT, int(raw)))
    except ValueError:
        return DEFAULT_LIMIT


def handler(event, context):
    limit = _parse_limit(event.get("queryStringParameters"))

    items = table.scan(ConsistentRead=True).get("Items", [])
    items.sort(key=lambda item: item.get("ingestedAt", ""), reverse=True)

    return json_response(200, {"documents": items[:limit]})
