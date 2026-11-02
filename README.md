# uae-job-engine

A small data pipeline that collects junior data, analytics, AI, software and IT job postings in the UAE, twice a day, on GitHub Actions.

It reads the public JSON, RSS or HTML listings behind employer career sites, the job systems that search engines barely index:

- **Oracle Recruiting Cloud**: ADIB, Emirates NBD, Emirates Islamic, FAB, Mashreq, du, e&, Emaar, DP World, Dubai Airports, AD Ports, NMC, PureHealth, SEHA, SSMC, Aster, KPMG Lower Gulf, Dell, Oracle
- **Workday**: Mastercard, Salesforce, HP, Shell, Baker Hughes, KBR, GSK, AstraZeneca, Novartis, Pfizer, Philips, Thomson Reuters and other multinationals with UAE offices
- **Phenom** (ADCB, G42, Majid Al Futtaim), **SAP SuccessFactors** (EY, PwC Middle East, Al-Futtaim), **Jibe** (M42), **Avature** (Dubai Holding) and **Attrax** (talabat) career sites, and Deriv's own job feed
- **Greenhouse, Lever, Ashby, Workable, Pinpoint, Teamtailor**: UAE startups and scale-ups (Careem, Tamara, Tabby, Chalhoub, Property Finder and more), plus a periodic probe that discovers new boards
- **Amazon** job search (UAE only)
- **JobSpy** (once a day, low volume, no login): LinkedIn, Indeed and Bayt. Google is off: it returned no data on every query in November 2026.

Each posting is filtered to the UAE and to junior roles in the target lanes. Senior titles, nationals-only roles, roles asking 4+ years, roles that rule out visa sponsorship, frontend/mobile roles, and finance, audit, sales and security roles without a technical core are dropped. The rest are deduplicated across sources and ranked.

## Outputs (`data/`)

| File | What it is |
|---|---|
| `latest.md` | Readable table of every open matching role, newest first |
| `latest.json` | The same, machine-readable; read by the daily digest |
| `health.json` | Per-source status for the last run: ok, not found, failed or blocked, with counts |
| `rejected_sample.json` | Up to 60 filtered-out UAE roles per reason, spread across sources, for tuning filters |
| `seen.json`, `detail_cache.json` | Dedupe history and cached description checks |
| `discovered.json` | Startup boards found by the probe, with their UAE job counts |
| `history/<date>.json` | Roles first seen on that day |

## Running

- `.github/workflows/collect.yml` runs at 05:13 Dubai (full: job systems, JobSpy sites, board probe) and 12:43 Dubai (job systems only), and on code pushes (job systems only, so JobSpy stays at one run a day).
- Locally: `pip install -r requirements.txt` then `FULL_RUN=0 python run.py` (job systems only) or `python run.py`.
- Tests: `python -m tests.test_filters` and `python -m tests.test_offline_run` (no network needed).

## Config

- `config/employers.yaml`: employer job systems, startup boards and probe slugs. Oracle entries need their `sites` set: an unknown or inactive site number silently returns another site's jobs. `verified: true` means the employer's own careers page was checked to link to that tenant and site. A comment after the `jibe` section lists employers that were checked and are not collected, with the reason.
- `config/search.yaml`: JobSpy queries per site (28 a day).

Requests are sent one at a time per host with at least a one-second gap (longer where robots.txt sets a crawl-delay), under an identifying User-Agent. New collectors are added only for listings that robots.txt allows. A JobSpy site that blocks queries is recorded as blocked in `health.json`; there are no workarounds such as proxies or logged-in sessions.
