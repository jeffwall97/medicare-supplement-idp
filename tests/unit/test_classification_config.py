from idp_common.classification_config import CLASSIFICATION_RULES, classify_text


def test_every_rule_has_at_least_one_marker():
    for rule in CLASSIFICATION_RULES:
        assert rule["markers"]


def test_partial_marker_match_does_not_classify():
    # Only one of the two required MI markers present.
    result = classify_text("Blue Cross Blue Shield of Michigan enrollment form")
    assert result["state"] == "UNKNOWN"


def test_no_markers_present_falls_back_to_unknown():
    result = classify_text("")
    assert result == {
        "documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT",
        "state": "UNKNOWN",
        "variant": "DEFAULT",
    }
