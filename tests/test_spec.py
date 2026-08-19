import pytest

import research.spec as spec

_MINIMAL = """
[my_screen]
description = "A screen."
filters = [["marketcap", ">=", 1e9]]

[my_screen.rank]
top_n = 10
metrics = [["roic", "high", 1.0]]
"""


# ── what a well-formed file produces ─────────────────────────────────────────


def test_loads_builds_a_runnable_spec():
    parsed = spec.loads(_MINIMAL)["my_screen"]

    assert parsed.name == "my_screen"
    assert parsed.description == "A screen."
    assert parsed.fields() == ("marketcap", "roic")
    assert parsed.rank.top_n == 10
    assert spec.validate(parsed) == []


def test_a_collection_value_becomes_a_tuple():
    """`excludes_any` takes a list in TOML; FilterCondition stores tuples."""
    text = '[s]\nfilters = [["recent_event_codes", "excludes_any", ["31", "13"]]]\n'

    condition = spec.loads(text)["s"].filters.conditions[0]

    assert condition.value == ("31", "13")


def test_a_null_operator_row_takes_no_value():
    text = '[s]\nfilters = [["fcf_yield", "not_null"]]\n'

    condition = spec.loads(text)["s"].filters.conditions[0]

    assert condition.operator == "not_null"
    assert condition.value is None


def test_a_universe_table_overrides_the_default():
    text = "[s]\n[s.universe]\nrecent_trade_days = 5\n"

    assert spec.loads(text)["s"].universe.recent_trade_days == 5


def test_omitting_rank_leaves_the_spec_unranked():
    text = '[s]\nfilters = [["marketcap", ">=", 1e9]]\n'

    assert spec.loads(text)["s"].rank is None


# ── structural faults, which must not reach the engine ───────────────────────


def test_a_misspelled_key_is_rejected_rather_than_ignored():
    """`filterz` would otherwise produce a screen with no filters that runs
    happily over the whole universe."""
    with pytest.raises(spec.SpecError, match="unknown key"):
        spec.loads('[s]\nfilterz = [["marketcap", ">=", 1e9]]\n')


def test_a_rank_table_without_metrics_is_rejected():
    with pytest.raises(spec.SpecError, match="no metrics"):
        spec.loads("[s]\n[s.rank]\ntop_n = 10\n")


def test_filters_must_be_a_list_of_rows():
    with pytest.raises(spec.SpecError, match="must be a list of rows"):
        spec.loads('[s]\nfilters = "marketcap >= 1e9"\n')


def test_a_row_that_is_not_a_row_is_rejected():
    with pytest.raises(spec.SpecError, match=r"filters\[0\]"):
        spec.loads('[s]\nfilters = ["marketcap"]\n')


def test_invalid_toml_is_reported_as_such():
    with pytest.raises(spec.SpecError, match="invalid TOML"):
        spec.loads("[s\n")


def test_a_missing_file_names_the_path():
    with pytest.raises(spec.SpecError, match="cannot read"):
        spec.load("does_not_exist.toml")


# ── faults the constructors already catch, surfaced with context ─────────────


def test_an_unregistered_operator_is_rejected_at_parse_time():
    with pytest.raises(spec.SpecError, match="unregistered operator"):
        spec.loads('[s]\nfilters = [["pe", "=~", 10]]\n')


def test_a_bad_rank_direction_is_rejected_at_parse_time():
    text = '[s]\n[s.rank]\nmetrics = [["roic", "highest", 1.0]]\n'

    with pytest.raises(spec.SpecError, match="unregistered direction"):
        spec.loads(text)


def test_an_unknown_exchange_is_rejected_at_parse_time():
    text = '[s]\n[s.universe]\nexchanges = ["MOON"]\n'

    with pytest.raises(spec.SpecError, match="unregistered exchanges"):
        spec.loads(text)


# ── the registry layer still runs afterwards ─────────────────────────────────


def test_parsing_does_not_check_the_registry():
    """Structure and vocabulary are separate passes: a well-formed row naming a
    field that does not exist parses, then fails validation."""
    parsed = spec.loads('[s]\nfilters = [["marketcapp", ">=", 1e9]]\n')["s"]

    assert spec.validate(parsed) == ["unknown filter field 'marketcapp'"]


def test_an_operator_the_field_forbids_fails_validation_not_parsing():
    parsed = spec.loads('[s]\nfilters = [["recent_event_codes", ">=", "42"]]\n')["s"]

    problems = spec.validate(parsed)

    assert len(problems) == 1
    assert "does not accept operator" in problems[0]
