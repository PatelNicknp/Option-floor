"""The schedule healer decides from clocks and run lists. No network."""

from datetime import datetime, timezone

from watchdog import CLOSE, OPEN, decide, duplicate, is_exact_slot, keeper_decide, last_slot, next_check, schedule_gate, should_start_keeper

UTC = timezone.utc


def et(year, month, day, hour, minute):
    # Build via a known slot helper by parsing an ISO string with a fixed offset.
    # November and January dates below are standard time (UTC-5). July is daylight (UTC-4).
    offset = "-04:00" if 3 < month < 11 else "-05:00"
    text = "%04d-%02d-%02dT%02d:%02d:00%s" % (year, month, day, hour, minute, offset)
    return datetime.fromisoformat(text).astimezone(UTC)


def run(start, status="completed", conclusion="success", run_id=1):
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "created_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_started_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_monday_afternoon_makes_up_a_dropped_morning_cron():
    # Monday 9 Nov 2026, 3:14 p.m. Eastern. Morning slot was 10:15. Last real run was Friday night.
    now = et(2026, 11, 9, 15, 14)
    friday = et(2026, 11, 6, 21, 57)
    action, why = decide(now, [run(friday)])
    assert action == "dispatch", why
    assert "Mon 10:15 ET" in why


def test_a_slot_that_already_ran_is_left_alone():
    now = et(2026, 11, 9, 15, 14)
    started = et(2026, 11, 9, 10, 20)
    action, why = decide(now, [run(started)])
    assert action == "none", why


def test_saturday_does_not_invent_a_slot_when_friday_ran():
    now = et(2026, 11, 7, 12, 0)
    friday = et(2026, 11, 6, 18, 40)
    action, why = decide(now, [run(friday)])
    assert action == "none", why


def test_thanksgiving_has_no_slot():
    holiday = et(2026, 11, 26, 11, 0)
    assert last_slot(holiday) == et(2026, 11, 25, 18, 30)


def test_daylight_and_standard_crons_match_only_the_real_slot():
    summer = et(2026, 7, 15, 10, 15)  # 14:15 UTC
    winter = et(2026, 11, 9, 10, 15)  # 15:15 UTC
    assert is_exact_slot(summer) and is_exact_slot(winter)
    go, why = schedule_gate("15 14 * * 1-5", summer)
    assert go, why
    go, why = schedule_gate("15 15 * * 1-5", summer)
    assert not go, why
    go, why = schedule_gate("15 15 * * 1-5", winter)
    assert go, why
    go, why = schedule_gate("15 14 * * 1-5", winter)
    assert not go


def test_duplicate_guard_skips_the_second_start_for_one_slot():
    slot_run = run(et(2026, 11, 9, 10, 16), run_id=10)
    me = run(et(2026, 11, 9, 10, 40), run_id=11)
    skip, why = duplicate(me, [slot_run, me])
    assert skip, why
    first = run(et(2026, 11, 9, 10, 16), run_id=11)
    skip, why = duplicate(first, [first])
    assert not skip, why


def test_keeper_wakes_ten_minutes_after_the_next_slot():
    after = et(2026, 11, 6, 19, 0)  # Friday after the close
    check_at, slot = next_check(after, 10)
    assert slot == et(2026, 11, 9, 10, 15)
    assert check_at == et(2026, 11, 9, 10, 25)


def test_keeper_does_not_start_a_second_copy_and_does_not_repeat_a_slot():
    start, why = should_start_keeper([{"id": 4, "status": "in_progress"}])
    assert not start and "already" in why
    start, why = should_start_keeper([])
    assert start, why
    action, why = keeper_decide(et(2026, 11, 9, 10, 25), et(2026, 11, 9, 10, 15), [run(et(2026, 11, 9, 10, 16))])
    assert action == "none", why


def test_open_and_close_minutes():
    assert OPEN == (10, 15) and CLOSE == (18, 30)
