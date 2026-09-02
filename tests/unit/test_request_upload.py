import json
import os
import re
from unittest.mock import MagicMock

os.environ.setdefault("RAW_BUCKET", "raw-bucket")
os.environ.setdefault("TABLE_NAME", "enrollment-records")

from conftest import load_handler_module  # noqa: E402

app = load_handler_module("request_upload")

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _event(filename, email=None):
    event = {"body": json.dumps({"filename": filename})}
    if email:
        event["requestContext"] = {"authorizer": {"jwt": {"claims": {"email": email}}}}
    return event


def test_returns_presigned_url_and_creates_upload_record(monkeypatch):
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url.return_value = "https://s3.example/presigned"
    fake_table = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "RAW_BUCKET", "raw-bucket")

    result = app.handler(_event("application.pdf"), None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert UUID_RE.match(body["documentId"])
    assert body["uploadUrl"] == "https://s3.example/presigned"
    assert body["bucket"] == "raw-bucket"
    assert body["key"] == f"incoming/web/{body['documentId']}/application.pdf"

    presign_kwargs = fake_s3.generate_presigned_url.call_args.kwargs
    assert presign_kwargs["Params"]["Bucket"] == "raw-bucket"
    assert presign_kwargs["Params"]["Key"] == body["key"]
    assert "ContentType" not in presign_kwargs["Params"]

    item = fake_table.put_item.call_args.kwargs["Item"]
    assert item["documentId"] == body["documentId"]
    assert item["status"] == "UPLOADED"
    assert item["originalFilename"] == "application.pdf"
    assert item["uploadedBy"] is None


def test_records_uploader_email_from_jwt_claims(monkeypatch):
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url.return_value = "https://s3.example/presigned"
    fake_table = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "RAW_BUCKET", "raw-bucket")

    app.handler(_event("application.pdf", email="broker@example.com"), None)

    item = fake_table.put_item.call_args.kwargs["Item"]
    assert item["uploadedBy"] == "broker@example.com"


def test_sanitizes_unsafe_filename_characters(monkeypatch):
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url.return_value = "https://s3.example/presigned"
    fake_table = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "RAW_BUCKET", "raw-bucket")

    result = app.handler(_event("../../etc/passwd; rm -rf.pdf"), None)

    body = json.loads(result["body"])
    assert "/" not in body["key"].split("/", 3)[-1]
    assert ".." not in body["key"]


def test_missing_filename_defaults_safely(monkeypatch):
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url.return_value = "https://s3.example/presigned"
    fake_table = MagicMock()
    monkeypatch.setattr(app, "s3", fake_s3)
    monkeypatch.setattr(app, "table", fake_table)
    monkeypatch.setattr(app, "RAW_BUCKET", "raw-bucket")

    result = app.handler({"body": json.dumps({})}, None)

    assert result["statusCode"] == 201
    body = json.loads(result["body"])
    assert body["key"].endswith("document.pdf")
