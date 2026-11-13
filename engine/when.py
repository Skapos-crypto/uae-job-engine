"""What should this wake-up of the workflow do: a full run, a career-systems run, or nothing?

GitHub starts scheduled workflows late: 4.5 to 8 hours late for this repository in November 2026,
once more than 10. A cron line therefore cannot say when a run happens. Instead the workflow wakes
every half hour, and this script picks the first wake-up after each target time (Dubai time) to do
the work. Every other wake-up exits within seconds.

Prints "mode=full", "mode=systems" or "mode=skip" (the workflow appends it to $GITHUB_OUTPUT).
Standard library only: it runs before anything is installed.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

DUBAI = timezone(timedelta(hours=4))
MIN_GAP_HOURS = 12  # never two full runs closer together than this: the job sites are searched once a day


def moment(now, hhmm):
    """The most recent time of day hhmm (Dubai) that is not after now."""
    hour, minute = (int(x) for x in hhmm.split(":"))
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return at if at <= now else at - timedelta(days=1)


def parse(stamp):
    """'2026-11-13 05:13' (Dubai time, as run.py writes it) -> datetime, or None."""
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=DUBAI)
    except (TypeError, ValueError):
        return None


def decide(now, last_run, last_full, full_after, systems_after):
    """now, last_run, last_full: Dubai datetimes; the last two may be None (never).

    Full: no full run yet since the latest full_after moment, and none in the last 12 hours.
    A full run missed altogether (GitHub woke nothing in time) is made up at the next wake-up.
    Systems: no run of any kind yet since the latest systems_after moment."""
    if last_full is None or (last_full < moment(now, full_after)
                             and now - last_full >= timedelta(hours=MIN_GAP_HOURS)):
        return "full"
    if last_run is None or last_run < moment(now, systems_after):
        return "systems"
    return "skip"


def main():
    event = os.environ.get("EVENT_NAME", "schedule")
    now = datetime.now(DUBAI)
    if event == "push":
        mode, why = "systems", "a code push never searches the job sites"
    elif event == "workflow_dispatch":
        mode = "systems" if os.environ.get("INPUT_FULL", "1").strip() == "0" else "full"
        why = "started by hand"
    else:
        generated = {}
        try:
            with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "data", "latest.json"), encoding="utf-8") as fh:
                generated = json.load(fh).get("generated") or {}
        except (OSError, ValueError):
            pass
        last_run = parse(generated.get("dubai"))
        # data written before last_full existed: take the last run of any kind, so that the first
        # wake-up after an upgrade does not search the job sites a second time that day
        last_full = parse(generated.get("last_full")) or last_run
        full_after = os.environ.get("FULL_AFTER", "12:45")
        systems_after = os.environ.get("SYSTEMS_AFTER", "07:00")
        mode = decide(now, last_run, last_full, full_after, systems_after)
        why = "full run due after %s, career systems after %s; last full run %s, last run %s" % (
            full_after, systems_after, generated.get("last_full") or "not recorded",
            generated.get("dubai") or "never")
    print("wake-up at %s Dubai: %s (%s)" % (now.strftime("%Y-%m-%d %H:%M"), mode, why), file=sys.stderr)
    print("mode=%s" % mode)


if __name__ == "__main__":
    main()
