#!/usr/bin/env python3
"""Collect UAE job postings from employer job systems and job sites, keep the junior
data / analytics / software / AI / IT roles, dedupe them, and write data/latest.*.

FULL_RUN=1 (default): everything, including JobSpy sites and the weekly board probe.
FULL_RUN=0: employer job systems and known boards only (the midday refresh).
"""
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import yaml

from engine import sources
from engine.http import Http
from engine.util import (DUBAI, FACTS_VERSION, NO_SPONSOR_RE, OWN_VISA_RE, SOURCE_RANK, classify, city_of,
                         elsewhere, is_uae, job_key, min_years, nationals, score, seniority, today_dubai)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
AGGREGATOR_TYPES = {"indeed", "linkedin", "google", "bayt"}
STALE_DAYS = 21          # aggregator postings older than this are dropped
CARRY_DAYS = 3           # keep jobs from sources that did not run this time for this long
FORGET_DAYS = 60         # forget dedupe history after this long
MAX_DETAILS = 160        # cap on full-description fetches per run
PROBE_EVERY_DAYS = 6
WORKERS = 32             # threads only wait their turn: the Http client allows one request per host at a time
REJECTED_PER_REASON = 60
STUCK_AFTER = 3          # failed runs in a row before a source is called out in the status panel


def log(msg):
    print(msg, flush=True)


def load_json(name, default):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_seen():
    """seen.json re-keyed with the current job_key, so a change to how jobs are matched never
    makes known jobs new again: entries that now share a key keep the earliest first_seen."""
    seen = {}
    for v in load_json("seen.json", {}).values():
        k = job_key(v.get("employer"), v.get("title"))
        if k in seen:
            v = dict(v, first_seen=min(seen[k]["first_seen"], v["first_seen"]),
                     last_seen=max(seen[k]["last_seen"], v["last_seen"]))
        seen[k] = v
    return seen


def save_json(name, obj):
    os.makedirs(os.path.dirname(os.path.join(DATA, name)), exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)


def load_yaml(name):
    with open(os.path.join(ROOT, "config", name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------- collection

def timed(fn):
    """Run fn and return (fn(), ms), with the time taken attached to any exception as .ms."""
    started = time.time()
    try:
        return fn(), int((time.time() - started) * 1000)
    except Exception as e:
        e.ms = int((time.time() - started) * 1000)
        raise


def run_tasks(tasks, health, workers=WORKERS):
    """tasks: list of (source_id, callable). Returns list of raw jobs."""
    raw = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(timed, fn): sid for sid, fn in tasks}
        for fut in as_completed(futs):
            sid = futs[fut]
            entry = {"ok": False, "fetched": 0}
            try:
                (jobs, meta), ms = fut.result()
                entry["ms"] = ms
                raw.extend(jobs)
                entry.update(ok=True, fetched=len(jobs), meta=meta)
                log("ok    %-38s %4d jobs" % (sid, len(jobs)))
            except sources.NotFound as e:
                entry.update(error=str(e), not_found=True, ms=getattr(e, "ms", None))
                log("404   %-38s %s" % (sid, e))
            except Exception as e:
                entry.update(error="%s: %s" % (type(e).__name__, str(e)[:240]), ms=getattr(e, "ms", None))
                log("FAIL  %-38s %s" % (sid, entry["error"]))
            health[sid] = entry
    return raw


def probe_boards(http, slugs, known, health):
    """Try each slug on each startup ATS. Returns list of boards that answered."""
    tasks, hits = [], []
    for slug in slugs:
        for ats in sources.BOARD_FETCHERS:
            if (ats, slug) in known:
                continue
            board = {"token": slug, "ats": ats}
            tasks.append((ats, board))

    def attempt(ats, board):
        try:
            jobs, meta = sources.BOARD_FETCHERS[ats](http, board)
            return ats, board, jobs, None
        except Exception as e:
            return ats, board, [], e

    found_jobs = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for ats, board, jobs, err in ex.map(lambda t: attempt(*t), tasks):
            if err is None and jobs:  # empty boards are often dormant accounts
                uae = sum(1 for j in jobs if is_uae(j["location"]))
                hits.append({"ats": ats, "token": board["token"], "jobs": len(jobs), "uae_jobs": uae})
                found_jobs.extend(jobs)
                health["%s:%s" % (ats, board["token"])] = {"ok": True, "fetched": len(jobs), "probe": True}
    log("probe: %d candidates tried, %d boards answered" % (len(tasks), len(hits)))
    return hits, found_jobs


def collect(http, cfg, search, full, health):
    tasks = []
    for emp in cfg.get("oracle") or []:
        tasks.append(("oracle:%s" % emp["name"], lambda emp=emp: sources.oracle(http, emp)))
    for emp in cfg.get("workday") or []:
        tasks.append(("workday:%s" % emp["name"], lambda emp=emp: sources.workday(http, emp)))
    for kind in ("phenom", "successfactors", "jibe", "avature", "attrax"):
        for emp in cfg.get(kind) or []:
            fetch = getattr(sources, kind)
            tasks.append(("%s:%s" % (kind, emp["name"]), lambda emp=emp, fetch=fetch: fetch(http, emp)))

    discovered = load_json("discovered.json", {"checked": None, "boards": []})
    checked = discovered.get("checked")
    probe_due = bool(full and cfg.get("probe") and (
        not checked or (today_dubai() - datetime.strptime(checked, "%Y-%m-%d").date()).days >= PROBE_EVERY_DAYS))
    boards = list(cfg.get("boards") or [])
    known = {(b["ats"], b["token"]) for b in boards}
    if not probe_due:
        # between probes, fetch only discovered boards that actually had UAE jobs
        for b in discovered.get("boards", []):
            if b.get("uae_jobs", 0) > 0 and (b["ats"], b["token"]) not in known:
                boards.append({"ats": b["ats"], "token": b["token"]})
    for b in boards:
        fetch = sources.BOARD_FETCHERS[b["ats"]]
        tasks.append(("%s:%s" % (b["ats"], b["token"]), lambda b=b, fetch=fetch: fetch(http, b)))
    if cfg.get("amazon"):
        tasks.append(("amazon", lambda: sources.amazon(http)))
    if cfg.get("deriv"):
        tasks.append(("deriv", lambda: sources.deriv(http)))

    # JobSpy's sites share no host with the employer systems, so it runs alongside them
    with ThreadPoolExecutor(max_workers=1) as background:
        jobspy = background.submit(run_jobspy, search.get("jobspy") or {}, health) if full else None
        raw = run_tasks(tasks, health)
        if probe_due:
            # re-probe every candidate slug on every startup ATS; the result replaces the old list
            hits, jobs = probe_boards(http, cfg["probe"], known, health)
            raw.extend(jobs)
            save_json("discovered.json", {"checked": str(today_dubai()), "boards": hits})
        if jobspy:
            raw.extend(jobspy.result())
    return raw


def run_jobspy(sites, health):
    """Each site is its own host, so the sites run side by side; within a site the queries
    stay one at a time with pauses (sources.jobspy_site)."""
    if not sites:
        return []
    try:
        import jobspy  # noqa: F401  imported once here so a broken install fails cleanly, not per thread
    except Exception as e:
        for site in sites:
            health["jobspy:%s" % site] = {"ok": False, "fetched": 0, "error": "import: %s" % str(e)[:200]}
        log("FAIL  jobspy import: %s" % e)
        return []

    def one(site, queries):
        started = time.time()
        try:
            jobs, meta = sources.jobspy_site(site, queries, log)
            entry = {"ok": meta["queries_ok"] > 0, "fetched": len(jobs), "meta": meta}
            if meta["blocked"]:
                entry["blocked"] = meta["blocked"]
        except Exception as e:
            jobs, entry = [], {"ok": False, "fetched": 0, "error": str(e)[:240]}
        entry["ms"] = int((time.time() - started) * 1000)
        return site, jobs, entry

    raw = []
    with ThreadPoolExecutor(max_workers=len(sites)) as ex:
        for site, jobs, entry in ex.map(lambda kv: one(*kv), sites.items()):
            raw.extend(jobs)
            health["jobspy:%s" % site] = entry
            if "error" in entry:
                log("FAIL  jobspy:%s %s" % (site, entry["error"]))
            else:
                m = entry["meta"]
                log("jobspy %-8s %4d jobs (%d/%d queries ok, %d blocked, %d skipped)" % (
                    site, len(jobs), m["queries_ok"], m["queries"], m["blocked"], m.get("skipped", 0)))
    return raw


# ---------------------------------------------------------------- filtering

def prefilter(job):
    """Cheap checks on title and location. Returns (family, cv, seniority) or (None, reason, None)."""
    if not job.get("title"):
        return None, "no-title", None
    if not is_uae(job.get("location")):
        return None, "not-uae", None
    if elsewhere(job["title"]):
        return None, "title-elsewhere", None
    family, cv = classify(job["title"])
    if family is None:
        return None, cv, None
    level = seniority(job["title"])
    if level == "senior":
        return None, "senior", None
    return family, cv, level


def detail_key(job):
    """Cache key for facts read from one posting's own page: its URL, not the job key, so a
    change to how jobs are matched never throws the cache away."""
    return "u:" + hashlib.sha1(job["url"].encode("utf-8")).hexdigest()[:16]


def cached_facts(cache, job):
    """Facts from an earlier full description, if they were worked out with today's patterns."""
    facts = cache.get(detail_key(job))
    return facts if facts and facts.get("v") == FACTS_VERSION else None


def fetch_details(http, jobs, cache, health):
    """Fill in full descriptions for employer jobs whose list entry has only a summary.
    Jobs already checked on an earlier run are answered from the cache instead."""
    need = [j for j in jobs if j.get("_detail") and not cached_facts(cache, j)]
    need = need[:MAX_DETAILS]

    def one(j):
        kind = j["_detail"][0]
        try:
            if kind == "oracle":
                return j, sources.oracle_detail(http, *j["_detail"][1:]), None
            if kind == "workday":
                return j, sources.workday_detail(http, *j["_detail"][1:]), None
            if kind == "phenom":
                return j, sources.phenom_detail(http, *j["_detail"][1:]), None
            if kind == "successfactors":
                return j, sources.successfactors_detail(http, *j["_detail"][1:]), None
            if kind == "avature":
                return j, sources.avature_detail(http, *j["_detail"][1:]), None
        except Exception as e:
            return j, "", e
        return j, "", None

    failures = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for j, found, err in ex.map(one, need):
            if err is not None:
                failures += 1
            else:
                j["_fresh_detail"] = True
                text, where = found if isinstance(found, tuple) else (found, "")
                if where:  # the job page states the location the list left out
                    j["location"] = j["_detail_location"] = where
                if text:
                    j["desc"] = (j.get("desc") or "") + " " + text
    health["_details"] = {"ok": failures == 0, "fetched": len(need) - failures, "failed": failures,
                          "skipped_cached": sum(1 for j in jobs if j.get("_detail") and cached_facts(cache, j))}
    log("details: %d fetched, %d failed" % (len(need) - failures, failures))


def final_checks(job, today, cache):
    """Description-level checks. Returns a rejection reason, or None and fills in flags."""
    desc = job.get("desc") or ""
    complete = job.get("_fresh_detail") or not job.get("_detail")
    facts = None if complete else cached_facts(cache, job)
    if facts is None:
        facts = {"nat": nationals(job["title"], desc), "yrs": min_years(desc),
                 "ns": bool(NO_SPONSOR_RE.search(desc)), "ov": bool(OWN_VISA_RE.search(desc))}
        if job.get("_detail_location"):
            facts["loc"] = job["_detail_location"]
        if job.get("_fresh_detail"):  # only a job page's facts are worth keeping; lists are re-read
            cache[detail_key(job)] = dict(facts, d=str(today), v=FACTS_VERSION)
    else:
        facts["d"] = str(today)
    if facts.get("loc"):
        job["location"] = facts["loc"]
    if not is_uae(job["location"]):  # only a job page can say so; the list passed the UAE check
        return "not-uae"
    nat, yrs = facts.get("nat"), facts.get("yrs")
    if nationals(job["title"], "") == "only":
        nat = "only"
    if nat == "only":
        return "nationals-only"
    if yrs is not None and yrs >= 4:
        return "4+ years"
    if facts.get("ns"):
        return "no-sponsorship"
    posted = job.get("posted")
    age = (today - posted).days if posted else None
    if job["source_type"] in AGGREGATOR_TYPES and age is not None and age > STALE_DAYS:
        return "stale"
    flags = []
    if nat == "preferred":
        flags.append("nationals_preferred")
    if yrs == 3:
        flags.append("stretch_3y")
    if facts.get("ov"):
        flags.append("own_visa_preferred")
    job.update(flags=flags, age_days=age, min_years=yrs, nat=nat)
    return None


# ---------------------------------------------------------------- output

def update_streaks(health, today):
    """Failed runs in a row per source, kept across runs (a source that did not run this time
    keeps its count), so one that keeps failing stands out from a one-off."""
    today_s = str(today)
    streaks = load_json("streaks.json", {})
    for sid, h in health.items():
        if sid.startswith("_") or h.get("probe"):
            continue
        s = streaks.setdefault(sid, {"fails": 0, "last_ok": None})
        s["ran"] = today_s
        if h.get("ok"):
            s.update(fails=0, last_ok=today_s)
            s.pop("error", None)
        else:
            s["fails"] += 1
            s["error"] = (h.get("error") or ("blocked" if h.get("blocked") else "no query succeeded"))[:120]
    keep = str(today - timedelta(days=14))
    return {k: v for k, v in streaks.items() if v.get("ran", today_s) >= keep}


def run_status(health, streaks, records, today):
    """What the status panel shows: sources answering, failing and blocked, sources failing
    run after run, and where the last 7 days' new roles came from."""
    srcs = {k: v for k, v in health.items() if not k.startswith("_") and not v.get("probe")}
    blocked = {k: "%d of %d queries blocked%s" % (v["blocked"], v["meta"]["queries"], ", %d skipped" %
                                                   v["meta"]["skipped"] if v["meta"].get("skipped") else "")
               for k, v in srcs.items() if v.get("blocked")}
    failing = {k: (v.get("error") or "")[:100] for k, v in srcs.items() if not v.get("ok") and k not in blocked}
    week = {"jobspy": 0, "employer": 0}
    for back in range(1, 7):
        for r in load_json(os.path.join("history", "%s.json" % (today - timedelta(days=back))), []):
            week["jobspy" if r["source"].startswith("jobspy") else "employer"] += 1
    for r in records:
        if r["is_new"]:
            week["jobspy" if r["source"].startswith("jobspy") else "employer"] += 1
    return {"sources": len(srcs), "ok": sum(1 for v in srcs.values() if v.get("ok")), "failing": failing,
            "blocked": blocked,
            "failing_in_a_row": {k: v["fails"] for k, v in streaks.items() if v.get("fails", 0) >= STUCK_AFTER},
            "new_last_7_days": week}


def sample_rejected(rejected, per_reason=REJECTED_PER_REASON):
    """Up to per_reason rows for each reason, taken in turn from each source, so rare reasons
    and small sources are not crowded out by the first big employer."""
    groups = {}
    for x in rejected:
        groups.setdefault(x["reason"], {}).setdefault(x["source"], []).append(x)
    out = []
    for reason in sorted(groups):
        queues, picked = list(groups[reason].values()), []
        while queues and len(picked) < per_reason:
            picked += [q.pop(0) for q in queues][:per_reason - len(picked)]
            queues = [q for q in queues if q]
        out += picked
    return out


def to_record(j):
    return {
        "key": j["key"], "title": j["title"], "employer": j["employer"], "sector": j.get("sector") or "",
        "city": city_of(j["location"]), "location": j["location"][:160], "family": j["family"],
        "cv": j["cv"], "seniority": j["seniority"], "url": j["url"], "source": j["source"],
        "source_type": j["source_type"], "seen_on": sorted(j.get("seen_on", [j["source"]])),
        "posted": str(j["posted"]) if j.get("posted") else None, "age_days": j.get("age_days"),
        "min_years": j.get("min_years"), "flags": j.get("flags", []), "first_seen": j["first_seen"],
        "last_seen": j["last_seen"], "is_new": j["is_new"], "score": j["score"],
        "snippet": (j.get("desc") or "")[:280],
    }


FAMILY_LABEL = {
    "data_analyst": "Data analyst", "bi": "BI / reporting", "data_science": "Data science",
    "ai_ml": "AI / ML", "data_eng": "Data engineering", "product": "Product", "business": "Business analysis",
    "software": "Software / backend", "it": "IT", "analyst": "Analyst (other)", "graduate": "Graduate / intern",
}


def md_escape(text):
    return (text or "").replace("|", "/").replace("\n", " ").strip()


def found_on(r):
    """The sites a job was seen on, its own link's site first: "oracle", "linkedin + indeed"."""
    names = []
    for s in [r["source"]] + list(r.get("seen_on") or []):
        name = s.split(":")[1] if s.startswith("jobspy:") else s.split(":")[0]
        if name not in names:
            names.append(name)
    return " + ".join(names)


def status_lines(status, full):
    st, week = status, status["new_last_7_days"]
    lines = ["## Status", "",
             "- **Sources:** %d of %d answered%s" % (st["ok"], st["sources"], "" if full else
                                                       " (career systems only; LinkedIn, Indeed and Bayt "
                                                       "run once a day)")]
    if st["failing"]:
        lines.append("- **Failing this run:** " + "; ".join("%s (%s)" % (k, md_escape(v) or "error")
                                                         for k, v in sorted(st["failing"].items())))
    if st["blocked"]:
        lines.append("- **Blocked:** " + "; ".join("%s, %s" % kv for kv in sorted(st["blocked"].items())))
    if st["failing_in_a_row"]:
        lines.append("- **⚠️ Failing %d or more runs in a row:** %s" % (STUCK_AFTER, ", ".join(
            "%s (%d)" % kv for kv in sorted(st["failing_in_a_row"].items()))))
    lines += ["- **New roles in the last 7 days:** %d from LinkedIn, Indeed and Bayt; %d from employer "
              "sites and boards" % (week["jobspy"], week["employer"]), ""]
    return lines


def write_markdown(records, summary, health_rows, status, full):
    now = datetime.now(DUBAI).strftime("%d %b %Y %H:%M")
    lines = [
        "# UAE junior roles: %d open, %d new today" % (summary["total"], summary["new_today"]),
        "",
        "Updated %s Dubai time. Sorted new first, then by fit. "
        "Lanes: data, BI, data science, AI/ML, data engineering, product, business analysis, "
        "software/backend, IT, graduate programmes. Senior, nationals-only, 4+ years and "
        "frontend/mobile roles are filtered out." % now,
        "",
    ] + status_lines(status, full) + [
        "| # | New | Role | Employer | City | Lane | Posted | Found on | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(records, 1):
        notes = []
        if "nationals_preferred" in r["flags"]:
            notes.append("UAE nationals preferred")
        if "stretch_3y" in r["flags"]:
            notes.append("asks 3 yrs")
        if "own_visa_preferred" in r["flags"]:
            notes.append("prefers own visa")
        lines.append("| %d | %s | [%s](%s) | %s | %s | %s | %s | %s | %s |" % (
            i, "🆕" if r["is_new"] else "", md_escape(r["title"]), r["url"], md_escape(r["employer"]),
            r["city"], FAMILY_LABEL.get(r["family"], r["family"]), r["posted"] or "",
            found_on(r), "; ".join(notes)))
    lines += ["", "## Sources this run", "", "| Source | Status | Jobs fetched |", "|---|---|---|"]
    for sid, h in health_rows:
        status = "ok" if h.get("ok") else ("not found" if h.get("not_found") else "failed")
        if h.get("blocked"):
            status += ", %d of %d queries blocked" % (h["blocked"], h["meta"]["queries"])
            if h["meta"].get("skipped"):
                status += ", %d skipped" % h["meta"]["skipped"]
        lines.append("| %s | %s | %s |" % (sid, status, h.get("fetched", 0)))
    with open(os.path.join(DATA, "latest.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- main

def main():
    full = os.environ.get("FULL_RUN", "1") == "1"
    cfg = load_yaml("employers.yaml")
    search = load_yaml("search.yaml")
    today = today_dubai()
    http = Http(min_interval=1.0)
    health = {}
    t0 = time.time()

    raw = collect(http, cfg, search, full, health)
    log("collected %d raw postings in %.0fs" % (len(raw), time.time() - t0))

    seen = load_seen()
    cache = load_json("detail_cache.json", {})
    rejected = []
    candidates = []
    for j in raw:
        family, cv_or_reason, level = prefilter(j)
        if family is None:
            if cv_or_reason != "not-uae":
                rejected.append({"title": j.get("title"), "employer": j.get("employer"),
                                 "source": j.get("source"), "reason": cv_or_reason, "url": j.get("url")})
            continue
        j.update(family=family, cv=cv_or_reason, seniority=level, key=job_key(j["employer"], j["title"]))
        candidates.append(j)

    fetch_details(http, candidates, cache, health)

    accepted = []
    for j in candidates:
        reason = final_checks(j, today, cache)
        if reason:
            rejected.append({"title": j["title"], "employer": j["employer"], "source": j["source"],
                             "reason": reason, "url": j.get("url")})
            continue
        accepted.append(j)

    # dedupe across sources: keep the employer's own link when we have it
    merged = {}
    for j in accepted:
        k = j["key"]
        if k not in merged:
            j["seen_on"] = {j["source"]}
            merged[k] = j
            continue
        m = merged[k]
        m["seen_on"].add(j["source"])
        if SOURCE_RANK.get(j["source_type"], 9) < SOURCE_RANK.get(m["source_type"], 9):
            for field in ("url", "source", "source_type", "sector", "employer"):
                if j.get(field):
                    m[field] = j[field]
        if j.get("posted") and (not m.get("posted") or j["posted"] < m["posted"]):
            m["posted"] = j["posted"]

    # stamp first/last seen, score
    today_s = str(today)
    for k, j in merged.items():
        prev = seen.get(k, {})
        j["first_seen"] = prev.get("first_seen", today_s)
        j["last_seen"] = today_s
        j["is_new"] = j["first_seen"] == today_s
        j["score"] = score(j)
        seen[k] = {"first_seen": j["first_seen"], "last_seen": today_s, "title": j["title"],
                   "employer": j["employer"]}

    records = [to_record(j) for j in merged.values()]

    # carry over jobs whose source did not run successfully this time
    previous = load_json("latest.json", {}).get("jobs", [])
    have = {r["key"] for r in records}
    carried = 0
    for r in previous:
        r["key"] = job_key(r["employer"], r["title"])  # records saved under an older key
        if r["key"] in have:
            continue
        src_ok = any(h.get("ok") for sid, h in health.items() if sid == r["source"])
        recent = (today - datetime.strptime(r["last_seen"], "%Y-%m-%d").date()).days <= CARRY_DAYS
        if not src_ok and recent:
            # the midday run skips JobSpy, so its morning finds are carried; they stay new all day
            r["is_new"] = r["first_seen"] == today_s
            records.append(r)
            have.add(r["key"])
            carried += 1

    records.sort(key=lambda r: (not r["is_new"], -r["score"], r["title"]))

    cutoff = today - timedelta(days=FORGET_DAYS)
    seen = {k: v for k, v in seen.items()
            if datetime.strptime(v["last_seen"], "%Y-%m-%d").date() >= cutoff}
    cache = {k: v for k, v in cache.items()  # "u:" keys only: older entries were keyed by job key
             if k.startswith("u:") and datetime.strptime(v.get("d", today_s), "%Y-%m-%d").date() >= cutoff}

    by_family, by_source = {}, {}
    for r in records:
        by_family[r["family"]] = by_family.get(r["family"], 0) + 1
        by_source[r["source"].split(":")[0]] = by_source.get(r["source"].split(":")[0], 0) + 1
    summary = {
        "total": len(records), "new_today": sum(1 for r in records if r["is_new"]),
        "carried_over": carried, "raw_postings": len(raw), "by_family": by_family,
        "by_source": by_source, "http_calls": http.calls,
        "rejected": {},
    }
    for x in rejected:
        summary["rejected"][x["reason"]] = summary["rejected"].get(x["reason"], 0) + 1
    streaks = update_streaks(health, today)
    summary["status"] = run_status(health, streaks, records, today)

    generated = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "dubai": datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M"), "full_run": full}
    save_json("latest.json", {"generated": generated, "summary": summary, "jobs": records})
    save_json("seen.json", seen)
    save_json("detail_cache.json", cache)
    save_json("health.json", {"generated": generated, "sources": health})
    save_json("streaks.json", streaks)
    save_json("rejected_sample.json", sample_rejected(rejected))
    save_json(os.path.join("history", "%s.json" % today_s), [r for r in records if r["is_new"]])
    health_rows = sorted(health.items(), key=lambda kv: (kv[1].get("ok", False), kv[0]))
    write_markdown(records, summary, [(k, v) for k, v in health_rows if not v.get("probe")], summary["status"], full)
    log("done: %d jobs (%d new), %d carried, %d HTTP calls, %.0fs" % (
        summary["total"], summary["new_today"], carried, http.calls, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
