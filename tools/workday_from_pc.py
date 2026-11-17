"""Read the Workday employers from a PC and write their roles to data/latest_workday.md.

Why this exists. Since 16 November 2026 Workday answers "too many requests" to the servers GitHub
runs this collector on, at the first request of every run, while it answers a home connection. The
collector records that refusal and does not route around it: no proxy, no other network, no changed
headers. This script is the other way to see those roles: whoever owns the repository reads Workday
from their own PC, with the same client (one request every 2 seconds, the same User-Agent) and the
same filters, and the result goes into a file of its own. The main run never merges it; it only
links to it from the status panel while Workday refuses GitHub.

On a day when the collector's own run did read Workday, this script asks Workday nothing.

    python tools/workday_from_pc.py
        Read Workday and write data/latest_workday.md in this checkout. No git.

    python tools/workday_from_pc.py --publish --author-name NAME --author-email EMAIL
        For a checkout kept only for this job (it refuses to run in one with other changes): bring
        it up to date with origin/main, read, write the file, commit that one file and push it.
        A push of this file alone does not start the collector (see the workflow's paths).

    --state DIR   where the script remembers what each job page said and when it first saw a role
                  (default: .workday-state in the checkout, which git ignores)
    --log FILE    append what would be printed to FILE (for a scheduled task without a window)
    --force       read Workday even if the collector's own run read it
"""
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import run  # noqa: E402
from engine import sources  # noqa: E402
from engine.http import Http  # noqa: E402
from engine.util import DUBAI, job_key, score, today_dubai  # noqa: E402

FILE = "latest_workday.md"
TABLE = ["| # | New | Role | Employer | City | Lane | Posted | Found on | Notes |", "|---|---|---|---|---|---|---|---|---|"]


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)


def read(employers, state_dir, today):
    """Ask every Workday employer, apply the collector's checks. Returns (records, answered, refused, dropped)."""
    http, health = Http(min_interval=1.0), {}
    tasks = [("workday:%s" % e["name"], lambda e=e: sources.workday(http, e)) for e in employers]
    with contextlib.redirect_stdout(io.StringIO()):
        raw = run.run_tasks(tasks, health)
    answered = sorted(k.split(":", 1)[1] for k, v in health.items() if v.get("ok"))
    refused = {k.split(":", 1)[1]: (v.get("error") or "no answer")[:90] for k, v in health.items() if not v.get("ok")}
    candidates = []
    for j in raw:
        family, cv, level = run.prefilter(j)
        if family is None:
            continue
        j.update(family=family, cv=cv, seniority=level, key=job_key(j["employer"], j["title"]))
        candidates.append(j)
    cache = load(os.path.join(state_dir, "cache.json"), {})
    with contextlib.redirect_stdout(io.StringIO()):
        run.fetch_details(http, candidates, cache, health)  # each job page is read once, then remembered
    kept, dropped = {}, {}
    for j in candidates:
        why = run.final_checks(j, today, cache)
        if why:
            dropped[why] = dropped.get(why, 0) + 1
        else:
            kept.setdefault(j["key"], j)
    seen = load(os.path.join(state_dir, "seen.json"), {})
    records = []
    for key, j in kept.items():
        first = seen.setdefault(key, str(today))
        j.update(first_seen=first, last_seen=str(today), is_new=first == str(today))
        j["score"] = score(j)
        records.append(run.to_record(j))
    save(os.path.join(state_dir, "cache.json"), cache)
    save(os.path.join(state_dir, "seen.json"), seen)
    print("%d postings in the UAE, %d fit a lane, %d pass every check; dropped after reading: %s"
          % (len(raw), len(candidates), len(records), dropped or "none"))
    return records, answered, refused, dropped


def render(records, github_keys, answered, total, refused, read_at, today):
    """The file's text: roles the main list lacks first, each part ordered as latest.md orders it."""
    def arrange(rows):
        core = sorted((r for r in rows if r["track"] == "core"), key=lambda r: (not r["is_new"], -r["score"], r["title"]))
        wide = sorted((r for r in rows if r["track"] == "wide"),
                      key=lambda r: (r["posted"] or r["first_seen"], r["score"]), reverse=True)
        return core + wide

    missing = arrange([r for r in records if r["key"] not in github_keys])
    listed = arrange([r for r in records if r["key"] in github_keys])
    lines = [
        "# Workday roles, read from a PC", "", "<!-- read: %s -->" % read_at,
        "Workday answers \"too many requests\" to the servers this collector runs on, so its employers are read "
        "from the repository owner's PC instead: the same client, pace and filters as [latest.md](latest.md), on "
        "days that PC is on. Read %s Dubai time: %d of %d employers answered, %d roles pass the filters. 🆕 marks "
        "a role read for the first time that day." % (read_at, answered, total, len(records)), ""]
    if refused:
        lines += ["**Did not answer:** " + "; ".join("%s (%s)" % (k, run.md_escape(v)) for k, v in sorted(refused.items())), ""]
    lines += ["## Not in latest.md (%d)" % len(missing), ""] + TABLE
    lines += [run.table_row(i, r, today) for i, r in enumerate(missing, 1)]
    lines += ["", "## Also in latest.md (%d)" % len(listed), ""] + TABLE
    lines += [run.table_row(i, r, today) for i, r in enumerate(listed, 1)]
    return "\n".join(lines) + "\n"


def render_idle(ok, total, last_read):
    """The file's text on a day when the collector's own run read Workday."""
    return "\n".join([
        "# Workday roles, read from a PC", "", "<!-- read: %s -->" % (last_read or "never"),
        "The collector's own run reads Workday again (%d of %d employers answered it), so those roles are in "
        "[latest.md](latest.md) and this file is not being refreshed. Last read from a PC: %s."
        % (ok, total, last_read or "never")]) + "\n"


def git(*args, check=True):
    p = subprocess.run(["git", "-C", REPO] + list(args), capture_output=True, text=True)
    if check and p.returncode:
        raise SystemExit("git %s failed: %s" % (" ".join(args[:3]), (p.stderr or p.stdout).strip()[:300]))
    return p


def update_checkout():
    """Bring a checkout kept for this job up to date. Refuses one that holds anybody's work."""
    other = [line for line in git("status", "--porcelain").stdout.splitlines() if not line.endswith("data/" + FILE)]
    if other:
        raise SystemExit("--publish needs a checkout kept only for it; this one has other changes: %s" % other[:3])
    git("checkout", "--", "data/" + FILE, check=False)  # a leftover of an interrupted run
    git("fetch", "--quiet", "origin", "main")
    if git("rev-list", "--count", "origin/main..HEAD").stdout.strip() != "0":
        raise SystemExit("--publish will not touch a checkout with commits that are not on origin/main")
    git("merge", "--ff-only", "--quiet", "origin/main")


def publish(name, email, stamp):
    """Commit the one file and push it; a push that lost a race is rebased and tried again."""
    who = ["-c", "user.name=" + name, "-c", "user.email=" + email]
    git("add", "data/" + FILE)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("nothing changed, nothing pushed")
        return
    git(*who, "commit", "--quiet", "-m", "workday: %s Dubai" % stamp)
    for _ in range(3):
        if git("push", "--quiet", "origin", "HEAD:main", check=False).returncode == 0:
            print("pushed data/%s" % FILE)
            return
        git("fetch", "--quiet", "origin", "main")
        git(*who, "rebase", "--quiet", "origin/main")
    raise SystemExit("could not push after three tries; the commit stays in this checkout")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read the Workday employers from this PC into data/latest_workday.md")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--author-name")
    ap.add_argument("--author-email")
    ap.add_argument("--state", default=os.path.join(REPO, ".workday-state"))
    ap.add_argument("--log")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    if args.log:
        sys.stdout = sys.stderr = open(args.log, "a", encoding="utf-8", buffering=1)
    print("--- %s" % datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M"))
    try:
        if args.publish and not (args.author_name and args.author_email):
            raise SystemExit("--publish needs --author-name and --author-email")
        if args.publish:
            update_checkout()
        os.makedirs(args.state, exist_ok=True)
        t0, today = time.time(), today_dubai()
        employers = run.load_yaml("employers.yaml").get("workday") or []
        state_path = os.path.join(args.state, "state.json")
        state = load(state_path, {})
        health = load(os.path.join(run.DATA, "health.json"), {}).get("sources", {})
        on_github = sum(1 for e in employers if health.get("workday:%s" % e["name"], {}).get("ok"))
        if employers and on_github * 5 >= len(employers) * 4 and not args.force:
            print("the collector's own run read Workday (%d of %d): nothing asked from here" % (on_github, len(employers)))
            text = render_idle(on_github, len(employers), state.get("last_read"))
        else:
            records, answered, refused, _ = read(employers, args.state, today)
            print("%d of %d Workday employers answered in %.0fs" % (len(answered), len(employers), time.time() - t0))
            if len(answered) * 2 < len(employers):
                print("too few answered: the file is left as it was. %s" % dict(list(refused.items())[:3]))
                return 1
            read_at = datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M")
            github_keys = {r["key"] for r in load(os.path.join(run.DATA, "latest.json"), {}).get("jobs", [])}
            text = render(records, github_keys, len(answered), len(employers), refused, read_at, today)
            state["last_read"] = read_at
            save(state_path, state)
        with open(os.path.join(run.DATA, FILE), "w", encoding="utf-8") as fh:
            fh.write(text)
        print("written: data/%s" % FILE)
        if args.publish:
            publish(args.author_name, args.author_email, datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M"))
        return 0
    except SystemExit as stop:
        print("stopped: %s" % stop)
        return 1
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
