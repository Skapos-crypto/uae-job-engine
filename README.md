# 🏙️ uae-job-engine

**A tiny robot that job-hunts in the UAE while you sleep.**

Twice a day, a free GitHub Actions run visits about 80 employer career sites and job boards, collects every opening it can find, throws away everything that isn't a junior role in data, BI, AI/ML, software or IT, and writes a tidy list of what's left. No servers, no accounts, no logins, no cost.

On a typical day it reads **~7,500 postings** and keeps **~100 roles** worth looking at.

> Built for one person's job search, shared so you can fork it for yours: another city, another country, another career. 🍴

---

## 🤔 Why this exists

Job boards only show part of the market. Many big employers (banks, telcos, airports, government-linked companies) post openings on their own career systems: Oracle, Workday, SuccessFactors, Phenom and friends. Search engines index those pages poorly, and the roles often never reach LinkedIn.

Every one of those career sites is backed by a public listing (JSON, RSS or plain HTML) that the site's own job search uses. This project reads those listings directly, politely, and puts everything in one place.

## 📬 What you get

Everything lands in [`data/`](data), refreshed after every run:

| File | What it is |
|---|---|
| [`latest.md`](data/latest.md) | 📋 A status panel, then a readable table of every matching role, newest first. Start here. |
| [`latest.json`](data/latest.json) | 🤖 The same list, machine-readable (handy for a digest email or a chatbot) |
| [`health.json`](data/health.json) | 🩺 Which sources worked this run, how many jobs each returned, and which were blocked |
| `streaks.json` | 📈 Failed runs in a row per source, so a source that keeps failing stands out from a one-off |
| [`rejected_sample.json`](data/rejected_sample.json) | 🗑️ Up to 60 dropped UAE roles per reason, for tuning the filters. A role dropped for its description carries the sentence that decided it (`why`) |
| `history/<date>.json` | 📅 Roles first seen on that day |
| `seen.json`, `detail_cache.json` | 🧠 Memory between runs: what's been seen, and what each job page said |

`latest.md` opens with a status panel:

> **Sources:** 82 of 83 answered · **Blocked:** jobspy:bayt, 2 of 9 queries blocked, 7 skipped · **LinkedIn pages:** 12 of 14 new roles read; 3 dropped after reading (2 nationals-only, 1 4+ years) · **New roles in the last 7 days:** 215 from LinkedIn, Indeed and Bayt; 9 from employer sites and boards

and then the list. A few rows:

| # | New | Role | Employer | City | Lane | Posted | Found on | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | 🆕 | Data Analyst - Intern | dubizzle Group | Dubai | Data analyst | 2026-10-21 | workable | |
| 2 | 🆕 | Software Engineer II - Backend | talabat | Dubai | Software / backend | | attrax | |
| 3 | | Data Analyst – Databricks AI/BI & FinOps | Etihad | Abu Dhabi | Data analyst | | linkedin + indeed | |

Each record in `latest.json` carries: `key, title, employer, sector, city, location, family, cv, seniority, url, source, source_type, posted, age_days, min_years, flags, first_seen, last_seen, is_new, score, snippet`. These field names are kept stable on purpose, so anything reading the file keeps working. `summary.status` holds the status panel's numbers.

## ⚙️ How it works

```mermaid
flowchart LR
    A[Employer career systems<br/>Oracle, Workday, Phenom,<br/>SuccessFactors, Avature...] --> C
    B[Startup boards<br/>Greenhouse, Lever, Ashby,<br/>Workable, Pinpoint, Teamtailor] --> C
    J[JobSpy, once a day<br/>LinkedIn, Indeed, Bayt] --> C
    C[Collect<br/>~7,500 postings] --> F{Filters}
    F -->|UAE? junior? right lane?| D[Read full descriptions<br/>employer pages, new LinkedIn roles<br/>nationals-only? 4+ years?<br/>no visa sponsorship?]
    D --> R[Merge duplicates and rank]
    R --> O[data/latest.md<br/>data/latest.json]
```

**One job, one row.** The same opening often appears on several sites, with the employer spelled differently ("Etihad" / "Etihad Airways", "Amazon" / "Amazon.com"), the title reworded ("Databricks Data Analyst" / "Data Analyst – Databricks"), a different city, or an agency's fresh reference code. Jobs are matched on fingerprints of the employer and the title that ignore all of that, so each job shows once, with every site it was found on, and a repost isn't announced as new.

| When (Dubai time) | What runs |
|---|---|
| 00:13 | 🌅 Full run: every career system, JobSpy, and every 6 days a probe that looks for new startup boards |
| 05:43 | ☀️ Career systems only |
| On every code push | 🔧 Career systems only, so testing a change never doubles the LinkedIn/Indeed/Bayt queries |

GitHub often starts scheduled runs late (6 to 8 hours late in November 2026), so these times are early enough for both runs to land before an afternoon digest either way. A full run takes a few minutes; a career-systems-only run about a minute.

## 🕵️ Where it looks

| System | Employers |
|---|---|
| **Oracle Recruiting Cloud** | ADIB, Emirates NBD, Emirates Islamic, FAB, Mashreq, du, e&, Emaar, DP World, Dubai Airports, AD Ports, NMC, PureHealth, SEHA, SSMC, Aster, KPMG Lower Gulf, Dell, Oracle |
| **Workday** | Mastercard, Salesforce, HP, Shell, Baker Hughes, KBR, GSK, AstraZeneca, Novartis, Pfizer, Philips, Coca-Cola, Thomson Reuters, Rolls-Royce, Cleveland Clinic Abu Dhabi |
| **Phenom** | ADCB, G42, Majid Al Futtaim |
| **SAP SuccessFactors** | EY, PwC Middle East, Al-Futtaim |
| **Avature** | Dubai Holding |
| **Jibe (iCIMS)** | M42 |
| **Attrax** | talabat |
| **Own feeds** | Amazon (UAE only), Deriv |
| **Startup boards** | Careem, Tamara, Tabby, Chalhoub, Property Finder, Ziina, Checkout.com, qlub, dubizzle, Aldar, Yassir, Bybit, OKX, Cohere, OpenAI, ElevenLabs and more |
| **JobSpy** (no login) | LinkedIn, Indeed and Bayt: 22 searches a day in total, plus up to 20 LinkedIn job pages |

Some big names aren't covered, and [`config/employers.yaml`](config/employers.yaml) says why for each one. Usually it's because their robots.txt says no, their jobs sit behind a login, or they only post on LinkedIn. Those still show up through the JobSpy searches.

## 🧹 The filters

Out of ~7,500 postings, a role survives only if:

- ✅ **It's in the UAE.** That includes titles like "Data Analyst – Riyadh, KSA" whose listing claims Dubai: those are caught and dropped.
- ✅ **It's in a target lane:** data analysis, BI, data science, AI/ML, data engineering, product, business analysis, software/backend, IT, or a graduate/intern programme.
- ✅ **It isn't senior.** Director, head, VP and principal titles are always out. Senior, lead and manager titles are out unless the title also says junior, graduate, trainee or similar ("Senior Associate" counts as senior).
- ✅ **It isn't a lookalike.** Sales, account executives, audit, tax, nursing, design, frontend/mobile and similar roles are dropped, and so are talent pools, career fairs and open applications. Finance and compliance titles survive only if they're clearly technical ("AML Data Analyst" stays).
- ✅ **It's still open.** LinkedIn, Indeed and Bayt postings older than 21 days are dropped; employer and board postings older than 120 days too (those are evergreen ads, not openings). Anything older than 30 days ranks lower.
- ✅ **The full description passes:**
  - Roles open only to UAE nationals are dropped. "Nationals preferred" roles are kept, flagged and ranked lower.
  - Roles asking for 4+ years of experience are dropped; 3 years is kept and flagged as a stretch.
  - Roles that say they won't sponsor a visa are dropped.
- 🏷️ **Agencies are marked, not dropped.** A posting by a recruitment agency or an unnamed ("Confidential") employer gets an `agency` flag, shows "agency or unnamed employer" in Notes, and ranks a little lower: expect a screening call first, and often a wish for candidates already in the country. The list of agency names is `AGENCY_RE` in [`engine/util.py`](engine/util.py).
- 🔗 **LinkedIn roles get the same checks.** LinkedIn's search results come without a description, so the full run opens the public page of each LinkedIn role that's new that day: up to 20 a day, best fit first, one page at a time. A page is read once; what it said is remembered. Jobs that another site already describes are skipped, and a copy of a job that came without any description takes the verdict of a copy that had one, so a nationals-only role can't sneak back in through the site that left the words out.

Every rule is pinned by a real title in [`tests/test_filters.py`](tests/test_filters.py) (100+ cases), so tuning one rule can't quietly break another.

## 🍴 Make it yours

Want this for Riyadh, London, or for marketing roles instead of data? Here's the recipe.

1. **Fork this repo.**
2. **Make it yours, not mine.** In [`engine/http.py`](engine/http.py), change `USER_AGENT` to point at *your* fork, so site owners can see who's visiting. Delete the files in `data/` to start with a clean history.
3. **Pick your employers** in [`config/employers.yaml`](config/employers.yaml). Remove the ones you don't care about and add your own (see the detective guide below).
4. **Pick your searches** in [`config/search.yaml`](config/search.yaml). Keep the daily total low (about 30). `linkedin_pages` caps the LinkedIn pages read a day; 0 switches the reading off.
5. **Teach it your lanes** in [`engine/util.py`](engine/util.py):
   - `UAE_RE` and `CITY_RE`: where you want to work
   - `FAMILIES`: which job titles you want
   - `EXCLUDE_RE`, `SENIOR_HARD_RE` and friends: what to throw away
   - The nationals-only rules are UAE-specific (Emiratisation); swap them for your country's equivalent, or remove them

   Then update [`tests/test_filters.py`](tests/test_filters.py) with titles you've actually seen, and run the tests.
6. **Turn on Actions** in your fork (the Actions tab; forks start with scheduled workflows off). The cron times in [`.github/workflows/collect.yml`](.github/workflows/collect.yml) are in UTC, so adjust them for your timezone.
7. **Wait for the first run**, then open `data/latest.md` and `data/health.json`. If the commit step fails with a permission error, check *Settings → Actions → General → Workflow permissions*.

## 🔎 Adding an employer: a little detective work

Open the employer's careers page, click through to a job, and look at the address bar or the page source. The job system usually gives itself away:

| If you see... | It's... | Add it under |
|---|---|---|
| `….oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1` | Oracle Recruiting Cloud | `oracle:` with `host` and `sites` |
| `….wd3.myworkdayjobs.com/SiteName` | Workday | `workday:` with `tenant`, `wd`, `site` |
| `phApp.ddo` in the page, URLs like `/global/en/job/123` | Phenom | `phenom:` with `base` |
| `/search/?q=&locationsearch=`, `/job/City-Title/123/` | SAP SuccessFactors | `successfactors:` with `base` |
| `….avature.net/…/JobDetail/…` | Avature | `avature:` |
| `boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, `apply.workable.com`, `….pinpointhq.com`, `….teamtailor.com` | Startup boards | `boards:` with `ats` and `token` |

**⚠️ The Oracle trap.** Oracle sites have numbers (`CX_1`, `CX_1001`, ...). If you guess one that's wrong or inactive, Oracle doesn't complain: it quietly returns *another* site's jobs. So the collector refuses to guess. List the real ones with

```
https://{host}/hcmRestApi/resources/latest/recruitingCESites?onlyData=true
```

pick one whose `StatusCode` is `ORA_ACTIVE`, and check it matches the link on the employer's careers page. An entry with no `sites` fails on purpose and lists the active ones for you.

Before adding a new kind of system, check its `robots.txt`. If it says no, it's a no. 🙅

## 💻 Run it on your own machine

```bash
pip install -r requirements.txt
FULL_RUN=0 python run.py   # career systems only, about a minute
python run.py              # everything, including JobSpy
python -m tests.test_filters
python -m tests.test_offline_run   # the whole pipeline against fake responses, no network
```

Local runs write to `data/`. Don't commit that: let the Actions run own `data/` (`git checkout -- data` before committing code).

## 🤝 Good manners

This project reads public listings that the sites' own job searches use, and it tries hard to be a polite guest:

- 🐢 **One request at a time per site**, at least a second apart, longer where a site's robots.txt asks for it
- 🏷️ **An honest User-Agent** that says what it is and links back here
- 🤖 **robots.txt is respected.** Sites that say no (some do) are listed as not collected, never worked around.
- 🔐 **No accounts, logins, cookies or proxies.** Ever.
- 📉 **Low volume:** two runs a day, 22 JobSpy searches a day in total, and at most 20 LinkedIn job pages, 4 to 8 seconds apart
- 🚫 **When a site blocks it,** that's recorded in `health.json`, and nothing tries to get around it. After two blocked searches in a row, the site is left alone for the rest of the run. The first refused LinkedIn page ends the page reading for the day, and no pages are read at all if LinkedIn refused the searches.

LinkedIn, Indeed and Bayt don't allow automated access in their terms. JobSpy usage here is deliberately tiny, and you can switch any site off by removing its list from `config/search.yaml` (and the LinkedIn page reading with `linkedin_pages: 0`). JobSpy sends its own browser-style headers, not the User-Agent above, for its searches and the LinkedIn pages alike.

## ❓ FAQ

**Does it apply to jobs for me?** No. It finds them; applying is still your job (and your cover letter's).

**Why doesn't it cover company X?** Check the "Checked ... and not collected" list in `config/employers.yaml`. If X isn't there, it probably just hasn't been looked at yet. Open an issue or a pull request!

**LinkedIn shows `blocked` in `health.json`. Is something broken?** No. LinkedIn sometimes refuses automated requests. The run records it and carries yesterday's LinkedIn roles over for up to three days.

**Can I get the list by email or in a chat app?** Point anything at `data/latest.json`. A small scheduled script or a chatbot can read it and send you a daily digest of roles where `is_new` is true.

**Is my data in here?** There's nothing personal in this repo: no CVs, emails or phone numbers. Please keep it that way in your fork, because it's public.

## 🙌 Contributing

Found a great junior role that got filtered out, or a senior one that slipped through? That's the most useful thing you can report. Open an issue with the title and the reason. Even better, add it to `tests/test_filters.py` and fix the rule in a pull request.

New employers, new job systems and better filters are all welcome. Please keep the good-manners rules above.

## 📜 License and disclaimer

The code is [MIT licensed](LICENSE): use it, fork it, change it, share it.

Not affiliated with any employer or job site listed here. Job data belongs to the employers who posted it; this tool only links back to their own pages. Listings change constantly, so always check the original posting before applying.
