"""Shared response helper for the web app's HTTP API Lambdas.

Handles the HttpApi payload-2.0 response shape and DynamoDB's Decimal
values, which json.dumps can't serialize on its own.
"""

import decimal
import json


def _default(obj):
    if isinstance(obj, decimal.Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def json_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }
