from idp_common.textract_queries import (
    DEFAULT_FIELD_MAP,
    DEFAULT_QUERIES,
    get_field_map_for_variant,
    get_queries_for_variant,
)


def test_unknown_variant_falls_back_to_default_queries():
    assert get_queries_for_variant("ZZ") == DEFAULT_QUERIES


def test_unknown_variant_falls_back_to_default_field_map():
    assert get_field_map_for_variant("ZZ") == DEFAULT_FIELD_MAP


def test_every_query_alias_has_a_field_mapping():
    query_aliases = {query["Alias"] for query in DEFAULT_QUERIES}
    assert query_aliases == set(DEFAULT_FIELD_MAP.keys())
