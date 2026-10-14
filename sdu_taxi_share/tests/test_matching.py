from services.matching import (GroupInfo, TripRequest, is_compatible, pick_best_group,
                               time_diff_minutes)


def req(**kw):
    base = dict(user_id=100, direction="to_sdu", district="almaly", date="2026-10-15",
                time="08:00", women_only=False, gender="m", window_min=15)
    base.update(kw)
    return TripRequest(**base)


def group(gid=1, members=((1, "m"),), **kw):
    base = dict(id=gid, direction="to_sdu", district="almaly", date="2026-10-15",
                time="08:00", women_only=False, window_min=15, status="open",
                member_ids=tuple(m[0] for m in members),
                member_genders=tuple(m[1] for m in members))
    base.update(kw)
    return GroupInfo(**base)


def test_time_diff():
    assert time_diff_minutes("08:00", "08:15") == 15
    assert time_diff_minutes("09:45", "08:00") == 105


def test_same_parameters_match():
    assert is_compatible(req(), group())


def test_window_boundary_15():
    assert is_compatible(req(time="08:15"), group())
    assert is_compatible(req(time="07:45"), group())
    assert not is_compatible(req(time="08:30"), group())
    assert not is_compatible(req(time="07:30"), group())


def test_extended_window_of_request_or_group():
    assert is_compatible(req(time="08:30", window_min=30), group())
    assert is_compatible(req(time="08:30"), group(window_min=30))
    assert not is_compatible(req(time="08:45", window_min=30), group())


def test_direction_district_date_must_match():
    assert not is_compatible(req(direction="to_almaty"), group())
    assert not is_compatible(req(district="medeu"), group())
    assert not is_compatible(req(date="2026-10-16"), group())


def test_group_size_limit():
    full = group(members=((1, "m"), (2, "m"), (3, "f"), (4, "f")), status="formed")
    assert not is_compatible(req(), full)
    three = group(members=((1, "m"), (2, "m"), (3, "f")), status="formed")
    assert is_compatible(req(), three)


def test_closed_groups_are_skipped():
    for status in ("completed", "cancelled"):
        assert not is_compatible(req(), group(status=status))


def test_user_not_matched_with_own_group():
    assert not is_compatible(req(user_id=1), group())


def test_women_only_group_rejects_men_and_unknown_gender():
    women_group = group(members=((1, "f"),), women_only=True)
    assert not is_compatible(req(gender="m"), women_group)
    assert not is_compatible(req(gender=None), women_group)
    assert is_compatible(req(gender="f"), women_group)


def test_women_only_request_needs_all_women_group():
    assert not is_compatible(req(gender="f", women_only=True), group(members=((1, "m"),)))
    assert not is_compatible(req(gender="f", women_only=True),
                             group(members=((1, "f"), (2, None)), status="formed"))
    assert is_compatible(req(gender="f", women_only=True), group(members=((1, "f"),)))


def test_pick_best_prefers_closest_time():
    groups = [group(1, time="08:10"), group(2, time="07:55"), group(3, time="08:15")]
    assert pick_best_group(req(), groups).id == 2


def test_pick_best_tie_prefers_bigger_then_older():
    small = group(1, time="08:05")
    big = group(2, time="07:55", members=((5, "m"), (6, "m")), status="formed")
    assert pick_best_group(req(), [small, big]).id == 2
    assert pick_best_group(req(), [group(7, time="08:05"), group(3, time="07:55")]).id == 3


def test_pick_best_none_when_nothing_fits():
    assert pick_best_group(req(), []) is None
    assert pick_best_group(req(), [group(time="09:00"), group(2, district="medeu")]) is None
