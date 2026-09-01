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


def test_classifies_georgia_form():
    result = classify_text("Anthem Blue Cross and Blue Shield\nApplication for Medicare Supplement and Anthem Extras - Georgia")
    assert result == {"documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT", "state": "GA", "variant": "GA"}


def test_classifies_tennessee_form():
    result = classify_text("BlueElite\nSubscriber Enrollment Application\nof Tennessee\nBlueCross BlueShield of Tennessee, Inc.")
    assert result == {"documentType": "MEDICARE_SUPPLEMENT_ENROLLMENT", "state": "TN", "variant": "TN"}


def test_georgia_and_tennessee_do_not_cross_match():
    # Anthem's GA form doesn't mention Tennessee/BlueElite, and vice versa.
    ga_text = "Anthem Blue Cross and Blue Shield Application for Medicare Supplement - Georgia"
    tn_text = "BlueElite Subscriber Enrollment Application BlueCross BlueShield of Tennessee"
    assert classify_text(ga_text)["state"] == "GA"
    assert classify_text(tn_text)["state"] == "TN"
