from conftest import load_handler_module

app = load_handler_module("classify_document")


def test_classifies_state_from_incoming_prefix():
    event = {"document": {"key": "incoming/ca/application.pdf"}}
    result = app.handler(event, None)
    assert result == {
        "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT",
        "state": "CA",
        "variant": "CA",
    }


def test_falls_back_to_default_variant_when_state_unknown():
    event = {"document": {"key": "application.pdf"}}
    result = app.handler(event, None)
    assert result["state"] == "UNKNOWN"
    assert result["variant"] == "DEFAULT"


def test_requires_state_segment_after_incoming():
    event = {"document": {"key": "incoming/application.pdf"}}
    result = app.handler(event, None)
    assert result["state"] == "UNKNOWN"
    assert result["variant"] == "DEFAULT"
