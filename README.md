# uae-job-engine

A small data pipeline that collects junior data, analytics, AI, software and IT job postings in the UAE, twice a day, on GitHub Actions.

It reads the public JSON behind employer career sites, the job systems that search engines barely index:

- **Oracle Recruiting Cloud**: ADIB, Emirates NBD, FAB, Mashreq, du, e&, Emaar, DP World, Dubai Airports, AD Ports, NMC, PureHealth, Oracle
- **Workday**: Mastercard, Rolls-Royce, KBR, Cleveland Clinic Abu Dhabi and other multinationals with UAE offices
- **Greenhouse, Lever, Ashby, Workable**: UAE startups and scale-ups, plus a periodic probe that discovers new boards
- **Amazon** job search
- **JobSpy** (once a day, low volume, no login): LinkedIn, Indeed, Google Jobs and Bayt

Each posting is filtered to the UAE and to junior roles in the target lanes. Senior titles, nationals-only roles, roles asking 4+ years, roles that rule out visa sponsorship, and frontend/mobile roles are dropped. The rest are deduplicated across sources and ranked.

## Outputs (`data/`)

| File | What it is |
|---|---|
| `latest.md` | Readable table of every open matching role, newest first |
| `latest.json` | The same, machine-readable; read by the daily digest |
| `health.json` | Per-source status for the last run: ok, not found or failed, with counts |
| `rejected_sample.json` | Sample of filtered-out UAE roles with the reason, for tuning filters |
| `seen.json`, `detail_cache.json` | Dedupe history and cached description checks |
| `history/<date>.json` | Roles first seen on that day |

## Running

- `.github/workflows/collect.yml` runs at 05:13 Dubai (full) and 12:43 Dubai (job systems only), and on code pushes.
- Locally: `pip install -r requirements.txt` then `FULL_RUN=0 python run.py` (job systems only) or `python run.py`.
- Tests: `python -m tests.test_filters` and `python -m tests.test_offline_run` (no network needed).

## Config

- `config/employers.yaml`: employer job systems, startup boards and probe slugs. `verified: false` entries are probes; check `data/health.json` and prune failures.
- `config/search.yaml`: JobSpy queries per site.

Requests are sent one at a time per host with at least a one-second gap, under an identifying User-Agent.
