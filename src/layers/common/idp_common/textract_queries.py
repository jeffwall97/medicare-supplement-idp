"""Textract Queries definitions for template-based extraction.

DEFAULT_* covers the fields common across states. Add per-state entries to
VARIANT_QUERIES / VARIANT_FIELD_MAPS as state-specific form variants are
onboarded (e.g. a state that asks an extra question or labels a field
differently). Textract allows a limited number of queries per request, so
keep each variant's list focused on what that form actually asks.
"""

DEFAULT_QUERIES = [
    {"Text": "What is the applicant's full name?", "Alias": "APPLICANT_NAME"},
    {"Text": "What is the applicant's date of birth?", "Alias": "APPLICANT_DOB"},
    {"Text": "What is the Medicare number?", "Alias": "MEDICARE_NUMBER"},
    {"Text": "What is the Medicare Part A effective date?", "Alias": "PART_A_EFFECTIVE_DATE"},
    {"Text": "What is the Medicare Part B effective date?", "Alias": "PART_B_EFFECTIVE_DATE"},
    {"Text": "What plan is being applied for?", "Alias": "PLAN_SELECTED"},
    {"Text": "What is the requested plan effective date?", "Alias": "PLAN_EFFECTIVE_DATE"},
    {"Text": "What is the applicant's street address?", "Alias": "APPLICANT_ADDRESS"},
    {"Text": "What is the applicant's phone number?", "Alias": "APPLICANT_PHONE"},
    {"Text": "Is this application replacing existing coverage?", "Alias": "REPLACING_COVERAGE"},
    {"Text": "What is the applicant's signature date?", "Alias": "SIGNATURE_DATE"},
]

DEFAULT_FIELD_MAP = {
    "APPLICANT_NAME": "applicantName",
    "APPLICANT_DOB": "applicantDateOfBirth",
    "MEDICARE_NUMBER": "medicareNumber",
    "PART_A_EFFECTIVE_DATE": "partAEffectiveDate",
    "PART_B_EFFECTIVE_DATE": "partBEffectiveDate",
    "PLAN_SELECTED": "planSelected",
    "PLAN_EFFECTIVE_DATE": "planEffectiveDate",
    "APPLICANT_ADDRESS": "applicantAddress",
    "APPLICANT_PHONE": "applicantPhone",
    "REPLACING_COVERAGE": "replacingExistingCoverage",
    "SIGNATURE_DATE": "signatureDate",
}

# Example of a state-specific override once onboarded:
# VARIANT_QUERIES = {
#     "CA": DEFAULT_QUERIES + [{"Text": "...", "Alias": "CA_SPECIFIC_FIELD"}],
# }
# VARIANT_FIELD_MAPS = {
#     "CA": {**DEFAULT_FIELD_MAP, "CA_SPECIFIC_FIELD": "caSpecificField"},
# }
VARIANT_QUERIES = {}
VARIANT_FIELD_MAPS = {}

# Fields that real enrollment forms typically represent as checkboxes rather
# than free text (a plan-selection row, a yes/no question). Textract Queries
# can't reliably read a checkbox's answer, so parse_and_validate falls back
# to Textract FORMS' SELECTION_ELEMENT blocks for these: each canonical field
# maps to the ordered list of checkbox labels that can appear next to it on
# the form, and whichever one comes back SELECTED is the answer.
DEFAULT_SELECTION_FIELDS = {
    "planSelected": ["A", "C", "D", "F", "HD-F", "G", "HD-G", "N"],
    "replacingExistingCoverage": ["Yes", "No"],
}

VARIANT_SELECTION_FIELDS = {
    # GA and TN's real forms label each plan checkbox "Plan A", "Plan G", etc.
    # (unlike MI's bare "A", "G"), and neither offers MI's High-Deductible F/G
    # options - matching each form's actual checkbox wording, per variant.
    "GA": {
        "planSelected": ["Plan A", "Plan F", "Plan G", "Plan N"],
        "replacingExistingCoverage": ["Yes", "No"],
    },
    "TN": {
        "planSelected": ["Plan A", "Plan D", "Plan G", "Plan N", "Plan C", "Plan F"],
        "replacingExistingCoverage": ["Yes", "No"],
    },
}


def get_queries_for_variant(variant):
    return VARIANT_QUERIES.get(variant, DEFAULT_QUERIES)


def get_field_map_for_variant(variant):
    return VARIANT_FIELD_MAPS.get(variant, DEFAULT_FIELD_MAP)


def get_selection_fields_for_variant(variant):
    return VARIANT_SELECTION_FIELDS.get(variant, DEFAULT_SELECTION_FIELDS)
