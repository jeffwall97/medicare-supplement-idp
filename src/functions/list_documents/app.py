"""GET /api/documents?limit=&status= -> recent documents, newest first.

Without a status filter: a single Scan (DynamoDB caps each response at 1MB,
comfortably enough items for this project's dev/demo scale) sorted by
ingestedAt in Python, since a Scan's own Limit stops after examining N items
in arbitrary order rather than returning the N most recent. If this ever
needs to handle real volume, replace with a GSI keyed on a constant
partition + ingestedAt sort key instead of scaling this up.

With a status filter: Query EnrollmentRecordsTable's existing StatusIndex
GSI (hash: status, range: ingestedAt) directly - already sorted newest-first
via ScanIndexForward=False, and correct at any volume unlike the Scan path
above (a Scan capped at `limit` items examined can easily miss every match
for a given status if newer documents of other statuses crowd it out).
"""

import os

import boto3
from boto3.dynamodb.conditions import Key
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
    query_params = event.get("queryStringParameters") or {}
    limit = _parse_limit(query_params)
    status = query_params.get("status")

    if status:
        result = table.query(
            IndexName="StatusIndex",
            KeyConditionExpression=Key("status").eq(status),
            ScanIndexForward=False,
            Limit=limit,
            ConsistentRead=False,
        )
        items = result.get("Items", [])
    else:
        items = table.scan(ConsistentRead=True).get("Items", [])
        items.sort(key=lambda item: item.get("ingestedAt", ""), reverse=True)
        items = items[:limit]

    return json_response(200, {"documents": items})
