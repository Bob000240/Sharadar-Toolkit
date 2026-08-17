import pandas as pd
import pytest

from research.filters import FilterCondition, Filters


def test_a_single_condition_accepts_a_generic_field_operator_and_value():
    """Was written against a standalone `apply_filter(frame, field, op, value)`,
    which 9c8e255 removed in favour of the one-condition Filters form. Null is
    not a pass: CCC has no value, so it cannot satisfy the threshold."""
    frame = pd.DataFrame(
        {"ticker": ["AAA", "BBB", "CCC"], "r_squared_60d": [0.8, 0.6, None]}
    )

    result = Filters(("r_squared_60d", ">=", 0.7)).apply(frame)

    assert result["ticker"].tolist() == ["AAA"]


def test_filters_apply_conditions_as_logical_and():
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC"],
            "roe": [0.20, 0.10, 0.30],
            "r_squared_60d": [0.80, 0.90, 0.50],
        }
    )

    result = Filters(
        FilterCondition("roe", ">", 0.15),
        ("r_squared_60d", ">=", 0.70),
    ).apply(frame)

    assert result["ticker"].tolist() == ["AAA"]


def test_equality_alias_and_between_are_supported():
    frame = pd.DataFrame(
        {"ticker": ["AAA", "BBB", "CCC"], "rsi_14": [30.0, 50.0, 70.0]}
    )

    equal = Filters(("ticker", "==", "BBB")).apply(frame)
    between = Filters(("rsi_14", "between", (30, 50))).apply(frame)

    assert equal["ticker"].tolist() == ["BBB"]
    assert between["ticker"].tolist() == ["AAA", "BBB"]


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("in", ("Technology", "Energy"), ["AAA", "CCC"]),
        ("not_in", ("Technology",), ["BBB", "CCC"]),
    ],
)
def test_categorical_operators_never_pass_nulls(operator, value, expected):
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "NULL"],
            "sector": ["Technology", "Finance", "Energy", None],
        }
    )

    result = Filters(("sector", operator, value)).apply(frame)

    assert result["ticker"].tolist() == expected


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("contains_any", ("EARNINGS", "BANKRUPTCY"), ["AAA", "BBB"]),
        ("contains_all", ("EARNINGS", "GUIDANCE"), ["AAA"]),
        ("excludes_any", ("BANKRUPTCY",), ["AAA", "CCC"]),
    ],
)
def test_collection_operators(operator, value, expected):
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "NULL"],
            "recent_event_codes": [
                ["EARNINGS", "GUIDANCE"],
                ["BANKRUPTCY"],
                [],
                None,
            ],
        }
    )

    result = Filters(("recent_event_codes", operator, value)).apply(frame)

    assert result["ticker"].tolist() == expected


def test_nulls_require_an_explicit_null_operator():
    frame = pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"], "roe": [0.2, None, 0.1]})

    not_equal = Filters(("roe", "!=", 0.2)).apply(frame)
    is_null = Filters(("roe", "is_null")).apply(frame)
    not_null = Filters(("roe", "not_null")).apply(frame)

    assert not_equal["ticker"].tolist() == ["CCC"]
    assert is_null["ticker"].tolist() == ["BBB"]
    assert not_null["ticker"].tolist() == ["AAA", "CCC"]


def test_funnel_reports_sequential_attrition_and_actual_null_drops():
    frame = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD"],
            "roe": [0.2, None, 0.1, 0.3],
            "sector": ["Technology", "Technology", "Energy", None],
        }
    )

    result = Filters(
        ("roe", ">=", 0.15),
        ("sector", "in", ("Technology",)),
    ).funnel(frame)

    assert result.to_dict("records") == [
        {
            "condition": "roe >= 0.15",
            "before": 4,
            "after": 2,
            "dropped": 2,
            "dropped_for_null": 1,
        },
        {
            "condition": "sector in ('Technology',)",
            "before": 2,
            "after": 1,
            "dropped": 1,
            "dropped_for_null": 1,
        },
    ]


def test_missing_fields_are_reported_before_filtering():
    frame = pd.DataFrame({"ticker": ["AAA"]})

    with pytest.raises(KeyError, match="r_squared_60d.*roe"):
        Filters(("roe", ">", 0), ("r_squared_60d", ">", 0)).apply(frame)


@pytest.mark.parametrize(
    "condition",
    [
        ("roe", "approximately", 0.2),
        ("roe", ">", None),
        ("sector", "in", "Technology"),
        ("roe", "between", (0.1,)),
        ("roe", "is_null", 0),
    ],
)
def test_invalid_conditions_fail_at_construction(condition):
    with pytest.raises(ValueError):
        Filters(condition)
