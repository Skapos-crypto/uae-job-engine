"""Which wake-up does the work. Run: python -m tests.test_when"""
from datetime import datetime

from engine.when import DUBAI, decide, moment, parse


def at(stamp):
    return datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=DUBAI)


def main():
    assert moment(at("2026-11-14 13:10"), "12:45") == at("2026-11-14 12:45")
    assert moment(at("2026-11-14 09:00"), "12:45") == at("2026-11-13 12:45")
    assert parse("2026-11-13 05:13") == at("2026-11-13 05:13") and parse(None) is None and parse("soon") is None

    full, systems = "12:45", "07:00"
    cases = [
        # now, last run of any kind, last full run, expected
        ("2026-11-14 06:37", "2026-11-13 13:20", "2026-11-13 13:05", "skip"),     # nothing due before 07:00
        ("2026-11-14 07:07", "2026-11-13 13:20", "2026-11-13 13:05", "systems"),  # first wake-up after 07:00
        ("2026-11-14 07:37", "2026-11-14 07:08", "2026-11-13 13:05", "skip"),     # the morning run is done
        ("2026-11-14 12:37", "2026-11-14 07:08", "2026-11-13 13:05", "skip"),     # not 12:45 yet
        ("2026-11-14 13:07", "2026-11-14 07:08", "2026-11-13 13:05", "full"),     # first wake-up after 12:45
        ("2026-11-14 13:37", "2026-11-14 13:20", "2026-11-14 13:20", "skip"),     # today's full run is done
        ("2026-11-14 23:37", "2026-11-14 13:20", "2026-11-14 13:20", "skip"),
        # GitHub woke nothing between 12:45 and midnight: the missed full run is made up at the next wake-up
        ("2026-11-15 01:07", "2026-11-14 07:08", "2026-11-13 13:05", "full"),
        # ... and the day's own run still follows, more than 12 hours later
        ("2026-11-15 13:07", "2026-11-15 07:10", "2026-11-15 01:20", "skip"),     # 11 h 47 min: too soon
        ("2026-11-15 13:37", "2026-11-15 07:10", "2026-11-15 01:20", "full"),
        # a full run 8 hours ago (the day the time moved from early morning to 12:45): no second search
        # of the job sites; the wake-up refreshes the career systems instead
        ("2026-11-14 13:07", "2026-11-14 05:13", "2026-11-14 05:13", "systems"),
        ("2026-11-14 17:37", "2026-11-14 13:10", "2026-11-14 05:13", "full"),     # 12 hours after it, the day's own run
        # a code push in the morning counts as that morning's career-systems run
        ("2026-11-14 07:37", "2026-11-14 07:20", "2026-11-13 13:05", "skip"),
        ("2026-11-14 07:07", "2026-11-14 06:20", "2026-11-13 13:05", "systems"),
        # a repository that has never run: everything at once
        ("2026-11-14 03:07", None, None, "full"),
    ]
    for now, last_run, last_full, expected in cases:
        got = decide(at(now), last_run and at(last_run), last_full and at(last_full), full, systems)
        assert got == expected, (now, last_run, last_full, "expected %s, got %s" % (expected, got))

    # the times in the workflow: career systems after 00:30, the full run after 12:00. GitHub starts the
    # 20:13 UTC line around 05:00 Dubai and the 01:43 UTC line around 12:35; the spare lines then find it done
    assert decide(at("2026-11-15 05:03"), at("2026-11-14 12:50"), at("2026-11-14 12:35"), "12:00", "00:30") == "systems"
    assert decide(at("2026-11-15 11:50"), at("2026-11-15 05:04"), at("2026-11-14 12:35"), "12:00", "00:30") == "skip"
    assert decide(at("2026-11-15 12:35"), at("2026-11-15 05:04"), at("2026-11-14 12:35"), "12:00", "00:30") == "full"
    assert decide(at("2026-11-15 13:10"), at("2026-11-15 12:47"), at("2026-11-15 12:35"), "12:00", "00:30") == "skip"
    assert decide(at("2026-11-15 19:40"), at("2026-11-15 12:47"), at("2026-11-15 12:35"), "12:00", "00:30") == "skip"
    # ... and if GitHub ever starts runs on time: 00:13 skips, 05:43 does the systems, 12:43 the full run
    assert decide(at("2026-11-15 00:13"), at("2026-11-14 12:55"), at("2026-11-14 12:43"), "12:00", "00:30") == "skip"
    assert decide(at("2026-11-15 05:43"), at("2026-11-14 12:55"), at("2026-11-14 12:43"), "12:00", "00:30") == "systems"
    assert decide(at("2026-11-15 06:13"), at("2026-11-15 05:44"), at("2026-11-14 12:43"), "12:00", "00:30") == "skip"
    assert decide(at("2026-11-15 12:43"), at("2026-11-15 05:44"), at("2026-11-14 12:43"), "12:00", "00:30") == "full"
    # the evening variant: full run after 17:00, career systems in the morning
    assert decide(at("2026-11-14 17:07"), at("2026-11-14 07:10"), at("2026-11-13 17:20"), "17:00", "07:00") == "full"
    assert decide(at("2026-11-14 16:37"), at("2026-11-14 07:10"), at("2026-11-13 17:20"), "17:00", "07:00") == "skip"
    # the early-morning variant used until November 2026: full after 04:30, career systems after 12:30
    assert decide(at("2026-11-14 04:37"), at("2026-11-13 12:50"), at("2026-11-13 05:13"), "04:30", "12:30") == "full"
    assert decide(at("2026-11-14 12:37"), at("2026-11-14 05:13"), at("2026-11-14 05:13"), "04:30", "12:30") == "systems"
    print("all %d wake-up cases pass" % (len(cases) + 16))


if __name__ == "__main__":
    main()
