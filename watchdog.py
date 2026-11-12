"""Make up a missed Options Floor run. Standard library only. Never calls Yahoo.

    python3 watchdog.py check          # if the latest New York slot has no run, start one
    python3 watchdog.py guard          # skip a scheduled or make-up run when that slot already ran
    python3 watchdog.py keeper         # sleep until each slot, make it up, then start the next keeper
    python3 watchdog.py ensure-keeper  # start a keeper when none is queued or running

Slots are 10:15 and 18:30 America/New_York, Monday to Friday, skipping NYSE holidays.
GitHub cron is best-effort and is listed for both standard time and daylight time.
The guard lets through only the cron that lands on a real slot, so summer and winter
do not double-fetch. A dropped cron is started once by the watchdog or the keeper,
and only until the next slot. A failed run is not retried here.
A research run that already started in the last four hours is not started again,
so a hand run cannot double-record paper trades or price history.

Switches in config.json (missing means on): features.self_heal_schedule, features.self_heal_keeper.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
NY = ZoneInfo("America/New_York")
WORKFLOW_FILE = "options-floor.yml"
KEEPER_FILE = "keeper.yml"
OPEN = (10, 15)
CLOSE = (18, 30)
GRACE_MIN = 20
# Four hours. Morning and evening slots are more than eight hours apart,
# so this only blocks a second run in the same window (a hand run plus a makeup).
OVERDUE_MIN = 240
KEEPER_DEFAULTS = {"check_after_min": 10, "chunk_min": 330, "min_gap_min": 240}
ACTIVE = {"queued", "in_progress", "waiting", "requested", "pending"}
NOT_A_RUN = {"cancelled", "skipped", "startup_failure", "stale"}
HEAL_REASONS = {"watchdog", "keeper", "keeper_retry"}
NYSE_HOLIDAYS = {dt.date.fromisoformat(d) for d in (
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
)}


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt(moment: dt.datetime) -> str:
    return moment.astimezone(NY).strftime("%a %H:%M ET")


def slots_for_day(day: dt.date) -> list[dt.datetime]:
    if day.weekday() >= 5 or day in NYSE_HOLIDAYS:
        return []
    out = []
    for hour, minute in (OPEN, CLOSE):
        out.append(dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY).astimezone(UTC))
    return out


def last_slot(at: dt.datetime) -> dt.datetime | None:
    """Latest intended slot at or before `at`, looking back a week."""
    day = at.astimezone(NY).date()
    for back in range(0, 8):
        due = [slot for slot in slots_for_day(day - dt.timedelta(days=back)) if slot <= at]
        if due:
            return due[-1]
    return None


def next_slot_after(slot: dt.datetime) -> dt.datetime | None:
    day = slot.astimezone(NY).date()
    for ahead in range(0, 12):
        for when in slots_for_day(day + dt.timedelta(days=ahead)):
            if when > slot:
                return when
    return None


def is_exact_slot(moment: dt.datetime) -> bool:
    local = moment.astimezone(NY)
    rounded = local.replace(second=0, microsecond=0)
    return rounded.astimezone(UTC) in slots_for_day(local.date()) and (local.hour, local.minute) in {OPEN, CLOSE}


def run_start(run: dict) -> dt.datetime | None:
    return parse_time(run.get("run_started_at") or run.get("created_at"))


def counts_as_run(run: dict) -> bool:
    if run.get("status") in ACTIVE:
        return True
    if run.get("conclusion") in NOT_A_RUN:
        return False
    return True


def latest_start(runs: list[dict]) -> dt.datetime | None:
    found = [start for run in runs if (start := run_start(run)) is not None and counts_as_run(run)]
    return max(found) if found else None


def decide(now: dt.datetime, runs: list[dict], enabled: bool = True) -> tuple[str, str]:
    """Return ('dispatch' or 'none', reason). One make-up of the latest slot, until the next slot."""
    if not enabled:
        return "none", "switch self_heal_schedule is off"
    active = [run for run in runs if run.get("status") in ACTIVE]
    if active:
        return "none", "a research run is already %s" % active[0].get("status")
    slot = last_slot(now - dt.timedelta(minutes=GRACE_MIN))
    if slot is None:
        return "none", "no expected slot"
    nxt = next_slot_after(slot)
    if nxt is not None and now >= nxt:
        return "none", "the next slot has started"
    latest = latest_start(runs)
    if latest is not None and latest >= slot:
        return "none", "slot %s already ran (last start %s)" % (fmt(slot), fmt(latest))
    if latest is not None and (now - latest).total_seconds() / 60.0 < OVERDUE_MIN:
        return "none", "last start %s is under %d min ago" % (fmt(latest), OVERDUE_MIN)
    return "dispatch", "missed slot %s; last start %s" % (fmt(slot), fmt(latest) if latest else "none")


def duplicate(me: dict, runs: list[dict]) -> tuple[bool, str]:
    created = parse_time(me.get("created_at"))
    if created is None:
        return False, "no start time, run as usual"
    slot = last_slot(created)
    if slot is None:
        return False, "no expected slot, run as usual"
    for run in runs:
        if str(run.get("id")) == str(me.get("id")):
            continue
        started = parse_time(run.get("created_at"))
        if started is None or not counts_as_run(run):
            continue
        if slot <= started < created or (started == created and int(run.get("id") or 0) < int(me.get("id") or 0)):
            return True, "run %s already covers slot %s" % (run.get("id"), fmt(slot))
    return False, "first run for slot %s" % fmt(slot)


def _field(spec: str, lo: int, hi: int) -> set[int]:
    if spec == "*":
        return set(range(lo, hi + 1))
    out: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            start, end = part.split("-")
            out.update(range(int(start), int(end) + 1))
        else:
            out.add(int(part))
    return out


def cron_fire_time(cron: str, created: dt.datetime) -> dt.datetime | None:
    try:
        minute, hour, dom, mon, dow = cron.split()
        if dom != "*" or mon != "*":
            return None
        minutes = _field(minute, 0, 59)
        hours = _field(hour, 0, 23)
        days = {item % 7 for item in _field(dow, 0, 7)}
    except Exception:
        return None
    cursor = created.replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 8):
        cron_dow = (cursor.weekday() + 1) % 7
        if cursor.minute in minutes and cursor.hour in hours and cron_dow in days:
            return cursor
        cursor -= dt.timedelta(minutes=1)
    return None


def schedule_gate(cron: str, created: dt.datetime) -> tuple[bool, str]:
    fired = cron_fire_time(cron or "", created)
    if fired is None:
        return True, "could not read the cron, run as usual"
    if is_exact_slot(fired):
        return True, "cron %s is the %s slot" % (cron, fmt(fired))
    return False, "cron %s fired for %s, which is not a New York slot" % (cron, fmt(fired))


def next_check(after: dt.datetime, check_after_min: int = 10) -> tuple[dt.datetime | None, dt.datetime | None]:
    lag = dt.timedelta(minutes=check_after_min)
    day = (after - lag).astimezone(NY).date()
    for ahead in range(0, 21):
        for when in slots_for_day(day + dt.timedelta(days=ahead)):
            if when + lag > after:
                return when + lag, when
    return None, None


def plan(now: dt.datetime, deadline: dt.datetime, after: dt.datetime | None = None, check_after_min: int = 10):
    when, slot = next_check(after if after is not None else now, check_after_min)
    if when is None or when > deadline:
        return "handoff", deadline, None
    return "check", when, slot


def keeper_decide(now: dt.datetime, slot: dt.datetime, runs: list[dict], min_gap_min: int = 240) -> tuple[str, str]:
    for run in runs:
        if run.get("status") in ACTIVE:
            return "none", "research run %s is %s" % (run.get("id"), run.get("status"))
        started = run_start(run)
        if started is not None and started >= slot and counts_as_run(run):
            return "none", "run %s started %s" % (run.get("id"), fmt(started))
    latest = latest_start(runs)
    if latest is not None and (now - latest).total_seconds() / 60.0 < min_gap_min:
        return "none", "last start %s is under %d min ago" % (fmt(latest), min_gap_min)
    return "dispatch", "missed slot %s; last start %s" % (fmt(slot), fmt(latest) if latest else "none")


def live_keepers(runs: list[dict], my_id=None) -> list[dict]:
    return [run for run in runs if run.get("status") in ACTIVE and str(run.get("id")) != str(my_id)]


def should_start_keeper(runs: list[dict], enabled: bool = True) -> tuple[bool, str]:
    if not enabled:
        return False, "switch self_heal_keeper is off"
    live = live_keepers(runs)
    if live:
        return False, "keeper %s is already %s" % (live[0].get("id"), live[0].get("status"))
    return True, "no live keeper"


def should_yield(my_id, runs: list[dict]) -> tuple[bool, str]:
    newer = [run for run in live_keepers(runs, my_id) if int(run.get("id") or 0) > int(my_id or 0)]
    if newer:
        return True, "newer keeper %s is %s" % (newer[0].get("id"), newer[0].get("status"))
    return False, ""


def feature_on(cfg: dict | None, key: str, default: bool = True) -> bool:
    features = (cfg or {}).get("features") or {}
    if key not in features:
        return default
    return bool(features[key])


def keeper_settings(cfg: dict | None) -> dict:
    out = dict(KEEPER_DEFAULTS)
    for key, value in ((cfg or {}).get("keeper") or {}).items():
        if key in out:
            out[key] = int(value)
    out["chunk_min"] = max(30, min(out["chunk_min"], 340))
    out["min_gap_min"] = max(15, out["min_gap_min"])
    out["check_after_min"] = max(5, out["check_after_min"])
    return out


def read_config(path: str = "config.json") -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _api(method: str, path: str, body: dict | None = None):
    repo = os.environ["GITHUB_REPOSITORY"]
    url = "https://api.github.com/repos/%s%s" % (repo, path)
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "OptionsFloor-watchdog",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def fetch_runs(n: int = 40) -> list[dict]:
    return _api("GET", "/actions/workflows/%s/runs?per_page=%d" % (WORKFLOW_FILE, n)).get("workflow_runs", [])


def fetch_keeper_runs(n: int = 20) -> list[dict]:
    return _api("GET", "/actions/workflows/%s/runs?per_page=%d" % (KEEPER_FILE, n)).get("workflow_runs", [])


def live_config() -> dict:
    try:
        repo = os.environ["GITHUB_REPOSITORY"]
        request = urllib.request.Request(
            "https://api.github.com/repos/%s/contents/config.json?ref=main" % repo,
            headers={
                "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                "Accept": "application/vnd.github.raw+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "OptionsFloor-watchdog",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except Exception as exc:
        print("could not read config.json from main (%s), using the checkout" % exc, flush=True)
        return read_config()


def _dispatch(workflow: str, inputs: dict, tries: int = 3) -> bool:
    for attempt in range(tries):
        try:
            _api("POST", "/actions/workflows/%s/dispatches" % workflow, {"ref": "main", "inputs": inputs})
            return True
        except Exception as exc:
            print("dispatch %s failed (%s), try %d of %d" % (workflow, exc, attempt + 1, tries), flush=True)
            time.sleep(20)
    return False


def ensure_keeper(cfg: dict | None = None, dry: bool = False) -> bool:
    cfg = read_config() if cfg is None else cfg
    try:
        runs = fetch_keeper_runs() if feature_on(cfg, "self_heal_keeper") else []
    except Exception as exc:
        print("ensure-keeper: could not read keeper runs (%s)" % exc, flush=True)
        return False
    start, why = should_start_keeper(runs, feature_on(cfg, "self_heal_keeper"))
    print("ensure-keeper:", "START" if start else "NONE", "-", why, flush=True)
    if start and not dry:
        return _dispatch(KEEPER_FILE, {})
    return False


def run_keeper(env: dict, now=None, sleep=time.sleep) -> str:
    clock = now or (lambda: dt.datetime.now(UTC).replace(microsecond=0))
    me = env.get("GITHUB_RUN_ID")
    cfg = live_config()
    settings = keeper_settings(cfg)
    started = clock()
    deadline = started + dt.timedelta(minutes=settings["chunk_min"])
    last = started - dt.timedelta(minutes=15)
    while True:
        if not feature_on(cfg, "self_heal_keeper"):
            print("keeper: switch is off, stopping", flush=True)
            return "off"
        try:
            yield_, why = should_yield(me, fetch_keeper_runs())
        except Exception as exc:
            yield_, why = False, ""
            print("keeper: could not read keeper runs (%s)" % exc, flush=True)
        if yield_:
            print("keeper: stepping aside -", why, flush=True)
            return "yield"
        kind, when, slot = plan(clock(), deadline, last, settings["check_after_min"])
        print("keeper: next %s at %s, sleeping %d s" % (kind, when.strftime("%Y-%m-%d %H:%M UTC"), max(0, int((when - clock()).total_seconds()))), flush=True)
        sleep(max(0, int((when - clock()).total_seconds())))
        cfg = live_config()
        settings = keeper_settings(cfg)
        if not feature_on(cfg, "self_heal_keeper"):
            continue
        if kind == "handoff":
            ok = _dispatch(KEEPER_FILE, {})
            print("keeper: handed off" if ok else "keeper: hand-off failed, the watchdog cron will restart one", flush=True)
            return "handoff"
        last = when
        try:
            runs = fetch_runs()
        except Exception as exc:
            print("keeper: could not read research runs (%s)" % exc, flush=True)
            continue
        action, why = keeper_decide(clock(), slot, runs, settings["min_gap_min"])
        print("keeper decision:", action.upper(), "-", why, flush=True)
        if action == "dispatch" and _dispatch(WORKFLOW_FILE, {"reason": "keeper"}):
            print("keeper: dispatched one research run", flush=True)


def run_guard(env: dict) -> bool:
    """Return True when this run should stop before fetching data."""
    event = env.get("EVENT_NAME", "")
    reason = (env.get("REASON") or "manual").strip().lower()
    if event == "workflow_dispatch" and reason not in HEAL_REASONS:
        print("guard: manual run, not skipped", flush=True)
        return False
    now = dt.datetime.now(UTC).replace(microsecond=0)
    try:
        runs = fetch_runs()
    except Exception as exc:
        print("guard: could not read runs (%s), run as usual" % exc, flush=True)
        return False
    me = next((run for run in runs if str(run.get("id")) == str(env.get("GITHUB_RUN_ID"))), None)
    if me is None:
        me = {"id": int(env.get("GITHUB_RUN_ID") or 0), "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if event == "schedule":
        go, why = schedule_gate(env.get("SCHEDULE", ""), parse_time(me.get("created_at")) or now)
        print("guard:", "RUN" if go else "SKIP", "-", why, flush=True)
        if not go:
            return True
    skip, why = duplicate(me, runs)
    print("guard:", "SKIP" if skip else "RUN", "-", why, flush=True)
    return skip


def _out(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("%s=%s\n" % (key, value))


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "check"
    if command == "keeper":
        run_keeper(os.environ)
        return 0
    if command == "ensure-keeper":
        dry = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
        ensure_keeper(dry=dry)
        return 0
    if command == "guard":
        skip = run_guard(os.environ)
        _out("skip", "true" if skip else "false")
        return 0
    dry = "--dry-run" in argv or os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}
    cfg = read_config()
    enabled = feature_on(cfg, "self_heal_schedule")
    now = dt.datetime.now(UTC)
    try:
        runs = fetch_runs() if enabled else []
    except Exception as exc:
        print("watchdog: could not read runs (%s), leaving the slot" % exc, flush=True)
        return 0
    action, why = decide(now, runs, enabled)
    print("watchdog decision:", action.upper(), "-", why, flush=True)
    _out("action", action)
    if action == "dispatch" and not dry:
        if _dispatch(WORKFLOW_FILE, {"reason": "watchdog"}):
            print("dispatched one research run", flush=True)
        else:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
