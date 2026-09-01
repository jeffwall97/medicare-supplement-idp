import json
import os

os.environ.setdefault("USER_POOL_CLIENT_ID", "test-client-id")
os.environ.setdefault("AWS_REGION", "us-east-1")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("get_auth_config")


def test_returns_client_id_and_region():
    result = app.handler({}, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"userPoolClientId": "test-client-id", "region": "us-east-1"}
