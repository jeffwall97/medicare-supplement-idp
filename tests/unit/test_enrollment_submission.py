import urllib.error
from unittest.mock import MagicMock

from idp_common import enrollment_submission


def test_build_xml_escapes_special_characters():
    xml_body = enrollment_submission.build_xml({"applicantName": "Jane & Doe <Jr>", "medicareNumber": "1EG4-TE5-MK72"})

    assert xml_body.startswith(b'<?xml version="1.0" encoding="UTF-8"?><InsuranceUpdate>')
    assert b"<applicantName>Jane &amp; Doe &lt;Jr&gt;</applicantName>" in xml_body
    assert b"<medicareNumber>1EG4-TE5-MK72</medicareNumber>" in xml_body


def test_submit_skips_when_no_endpoint():
    status, error = enrollment_submission.submit_to_enrollment_api(b"<xml/>", "")

    assert status == "SUBMISSION_SKIPPED"
    assert error is None


def test_submit_marks_submitted_on_2xx(monkeypatch):
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.__enter__.return_value = fake_response
    monkeypatch.setattr(enrollment_submission.urllib.request, "urlopen", MagicMock(return_value=fake_response))

    status, error = enrollment_submission.submit_to_enrollment_api(b"<xml/>", "https://enrollment.example.com")

    assert status == "SUBMITTED"
    assert error is None


def test_submit_marks_failed_on_non_2xx(monkeypatch):
    fake_response = MagicMock()
    fake_response.status = 500
    fake_response.__enter__.return_value = fake_response
    monkeypatch.setattr(enrollment_submission.urllib.request, "urlopen", MagicMock(return_value=fake_response))

    status, error = enrollment_submission.submit_to_enrollment_api(b"<xml/>", "https://enrollment.example.com")

    assert status == "SUBMISSION_FAILED"
    assert "500" in error


def test_submit_marks_failed_on_connection_error(monkeypatch):
    def raise_url_error(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(enrollment_submission.urllib.request, "urlopen", raise_url_error)

    status, error = enrollment_submission.submit_to_enrollment_api(b"<xml/>", "https://enrollment.example.com")

    assert status == "SUBMISSION_FAILED"
    assert "connection refused" in error
