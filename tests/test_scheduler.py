from scheduler.jobs import _parse_hhmm


def test_parse_hhmm_splits_hour_and_minute():
    assert _parse_hhmm("08:00") == (8, 0)
    assert _parse_hhmm("21:45") == (21, 45)
