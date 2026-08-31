from conftest import load_handler_module

app = load_handler_module("classify_document")


def test_classifies_known_form_from_detected_text():
    event = {
        "textDetection": {
            "text": "Blue Cross Medicare Supplement\nBlue Cross Blue Shield of Michigan\n2026 Medicare supplement application\n"
        }
    }
    result = app.handler(event, None)
    assert result == {
        "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT",
        "state": "MI",
        "variant": "MI",
    }


def test_unrecognized_text_falls_back_to_default_variant():
    event = {"textDetection": {"text": "Some unrelated document text"}}
    result = app.handler(event, None)
    assert result["state"] == "UNKNOWN"
    assert result["variant"] == "DEFAULT"


def test_matching_is_case_insensitive():
    event = {
        "textDetection": {
            "text": "BLUE CROSS BLUE SHIELD OF MICHIGAN medicare SUPPLEMENT enrollment"
        }
    }
    result = app.handler(event, None)
    assert result["state"] == "MI"
