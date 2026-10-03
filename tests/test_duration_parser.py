import pytest

from src.data.feature_engineering import parse_duration_seconds


@pytest.mark.parametrize("iso,expected", [
    ("PT4M20S", 260), ("PT1H", 3600), ("PT1H2M3S", 3723), ("PT45S", 45), ("PT0S", 0),
    ("P1DT2H", 93600), ("PT10M", 600),
])
def test_valid_durations(iso, expected):
    assert parse_duration_seconds(iso) == expected


@pytest.mark.parametrize("bad", [None, "", "abc", "4:20", float("nan")])
def test_invalid_durations_return_none(bad):
    assert parse_duration_seconds(bad) is None
