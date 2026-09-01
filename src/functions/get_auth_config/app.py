"""GET /api/config -> Cognito client info the frontend needs before login.

Public/unauthenticated (see its HttpApi Event's Auth: Authorizer: NONE
override in template.yaml) - the frontend calls this before a user has ever
logged in, to learn which User Pool Client to call SignUp/InitiateAuth
against. This is a static frontend with no build step to inject deploy-time
values, so this tiny endpoint stands in for that.
"""

import os

from idp_common.http_responses import json_response

USER_POOL_CLIENT_ID = os.environ["USER_POOL_CLIENT_ID"]
REGION = os.environ["AWS_REGION"]


def handler(event, context):
    return json_response(200, {"userPoolClientId": USER_POOL_CLIENT_ID, "region": REGION})
