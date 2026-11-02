"""Collectors. Each returns (jobs, meta). A job is a dict with:
source, source_type, employer, sector, title, location, posted (date|None), url, desc,
and optionally _detail, a tuple telling run.py how to fetch the full description later."""
import html
import json
import logging
import random
import re
import time
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree

from .util import UAE_RE, clean, parse_date, relative_posted, strip_html


class SourceError(Exception):
    pass


class NotFound(SourceError):
    pass


def _json(resp, what):
    if resp.status_code == 404:
        raise NotFound("%s: 404" % what)
    if resp.status_code >= 400:
        raise SourceError("%s: HTTP %s %s" % (what, resp.status_code, resp.text[:160].replace("\n", " ")))
    try:
        return resp.json()
    except ValueError:
        raise SourceError("%s: not JSON (%s)" % (what, resp.text[:120].replace("\n", " ")))


# ---------------------------------------------------------------- Oracle Recruiting Cloud

ORACLE_PAGE = 100
ORACLE_MAX_PAGES = 12


def oracle(http, emp):
    host = emp["host"]
    base = "https://%s/hcmRestApi/resources/latest" % host
    sites = list(emp.get("sites") or [])
    if not sites:
        # An unknown or inactive siteNumber silently returns another site's jobs, so never guess:
        # list the active career sites and fail until one is set in config/employers.yaml.
        data = _json(http.get("%s/recruitingCESites?onlyData=true&limit=200" % base), "sites")
        active = ["%s (%s)" % (i.get("SiteNumber"), clean(i.get("SiteName")))
                  for i in data.get("items") or [] if i.get("StatusCode") == "ORA_ACTIVE"]
        raise SourceError("no sites set; active career sites: %s" % (", ".join(active) or "none"))
    meta = {"sites": sites}

    out = {}
    for site in sites:
        offset = 0
        total = None
        page = ORACLE_PAGE
        for _ in range(ORACLE_MAX_PAGES * 4):
            finder = "findReqs;siteNumber=%s,limit=%d,offset=%d,sortBy=POSTING_DATES_DESC" % (
                site, page, offset)
            if emp.get("location_id"):
                finder += ",locationId=%s" % emp["location_id"]
            url = ("%s/recruitingCEJobRequisitions?onlyData=true"
                   "&expand=requisitionList.secondaryLocations&finder=%s" % (base, finder))
            resp = http.get(url)
            if resp.status_code == 400 and page > 25:
                page = 25  # some pods reject large pages; fall back to the career site's own size
                meta["page_fallback"] = True
                continue
            data = _json(resp, "requisitions %s" % site)
            items = data.get("items") or []
            if not items:
                break
            block = items[0]
            if total is None:
                total = block.get("TotalJobsCount") or 0
                meta.setdefault("totals", {})[site] = total
            reqs = block.get("requisitionList") or []
            for q in reqs:
                jid = clean(q.get("Id"))
                if not jid or jid in out:
                    continue
                locs = [clean(q.get("PrimaryLocation"))]
                locs += [clean(s.get("Name")) for s in (q.get("secondaryLocations") or [])]
                out[jid] = {
                    "source": "oracle:%s" % emp["name"],
                    "source_type": "employer",
                    "employer": emp["name"],
                    "sector": emp.get("sector", ""),
                    "title": clean(q.get("Title")),
                    "location": "; ".join(l for l in locs if l),
                    "posted": parse_date(q.get("PostedDate")),
                    "url": "https://%s/hcmUI/CandidateExperience/en/sites/%s/job/%s" % (host, site, jid),
                    "desc": strip_html(q.get("ShortDescriptionStr")),
                    "_detail": ("oracle", base, site, jid),
                }
            offset += len(reqs)
            if not reqs or (total and offset >= total) or (not total and len(reqs) < page):
                break
            if offset >= ORACLE_PAGE * ORACLE_MAX_PAGES:
                meta["capped"] = True
                break
    return list(out.values()), meta


def oracle_detail(http, base, site, jid):
    url = ("%s/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
           "&finder=ById;Id=%%22%s%%22,siteNumber=%s" % (base, jid, site))
    data = _json(http.get(url), "detail %s" % jid)
    items = data.get("items") or [{}]
    it = items[0]
    parts = [it.get(k) for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr",
                                 "ExternalQualificationsStr", "CorporateDescriptionStr")]
    return strip_html(" ".join(clean(p) for p in parts if p))


# ---------------------------------------------------------------- Workday

LOCATION_PARAM_PRIORITY = ("locationCountry", "locationRegionStateProvince", "locations",
                           "locationMainGroup", "Location_Country", "primaryLocation")


def _uae_facets(facets):
    """The site's own UAE location facet: ({param: [ids]}, [descriptors]), or ({}, [])."""
    found, names = {}, {}

    def walk(items, parent_param):
        for f in items or []:
            param = f.get("facetParameter") or parent_param
            for v in f.get("values") or []:
                if v.get("values"):
                    walk([v], v.get("facetParameter") or param)
                elif UAE_RE.search(clean(v.get("descriptor"))) and v.get("id"):
                    found.setdefault(param, []).append(v["id"])
                    names.setdefault(param, []).append(clean(v.get("descriptor")))

    walk(facets, None)
    for p in LOCATION_PARAM_PRIORITY + tuple(sorted(found)):
        if p in found:
            return {p: found[p]}, names[p]
    return {}, []


def workday(http, emp):
    tenant, wd, site = emp["tenant"], emp["wd"], emp["site"]
    host = "%s.%s.myworkdayjobs.com" % (tenant, wd)
    api = "https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    first = _json(http.post(api, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                            headers=headers), "workday %s" % tenant)
    applied, places = _uae_facets(first.get("facets"))
    meta = {"facets": applied, "all_jobs": first.get("total")}
    if not applied:
        return [], meta
    uae_label = places[0] if len(places) == 1 else "United Arab Emirates"
    jobs = []
    offset = 0
    total = None
    for _ in range(25):
        body = {"appliedFacets": applied, "limit": 20, "offset": offset, "searchText": ""}
        data = _json(http.post(api, json=body, headers=headers), "workday %s page" % tenant)
        if total is None:
            total = data.get("total") or 0
            meta["uae_total"] = total
        posts = data.get("jobPostings") or []
        for p in posts:
            path = clean(p.get("externalPath"))
            loc = clean(p.get("locationsText"))
            if not UAE_RE.search(loc):  # "2 Locations": the UAE facet already placed it in the UAE
                loc = "%s; %s" % (loc, uae_label) if loc else uae_label
            jobs.append({
                "source": "workday:%s" % emp["name"],
                "source_type": "employer",
                "employer": emp["name"],
                "sector": emp.get("sector", ""),
                "title": clean(p.get("title")),
                "location": loc,
                "posted": relative_posted(p.get("postedOn")),
                "url": "https://%s/en-US/%s%s" % (host, site, path),
                "desc": "",
                "_detail": ("workday", host, tenant, site, path),
            })
        offset += len(posts)
        if not posts or offset >= total:
            break
    return jobs, meta


def workday_detail(http, host, tenant, site, path):
    data = _json(http.get("https://%s/wday/cxs/%s/%s%s" % (host, tenant, site, path)), "workday detail")
    info = data.get("jobPostingInfo") or {}
    return strip_html(info.get("jobDescription"))


def _page(resp, what):
    if resp.status_code == 404:
        raise NotFound("%s: 404" % what)
    if resp.status_code >= 400:
        raise SourceError("%s: HTTP %s" % (what, resp.status_code))
    return resp.text


# ---------------------------------------------------------------- Phenom

PHENOM_DDO_RE = re.compile(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", re.S)
PHENOM_MAX = 500


def _phenom_ddo(resp, what):
    m = PHENOM_DDO_RE.search(_page(resp, what))
    if not m:
        raise SourceError("%s: no phApp.ddo in page" % what)
    return json.loads(m.group(1))


def phenom(http, emp):
    """Phenom career sites: each search-results page carries its jobs as JSON in phApp.ddo."""
    base = emp["base"].rstrip("/")
    jobs, total, offset = [], 0, 0
    while offset < PHENOM_MAX:
        ddo = _phenom_ddo(http.get("%s/search-results?from=%d&s=1" % (base, offset)), "phenom %s" % emp["name"])
        found = ddo.get("eagerLoadRefineSearch") or {}
        total = found.get("totalHits") or 0
        page = (found.get("data") or {}).get("jobs") or []
        for j in page:
            jid = clean(j.get("jobId"))
            locs = [clean(j.get("location"))] + [clean(x) for x in (j.get("multi_location") or [])]
            jobs.append({
                "source": "phenom:%s" % emp["name"],
                "source_type": "employer",
                "employer": emp["name"],
                "sector": emp.get("sector", ""),
                "title": clean(j.get("title")),
                "location": "; ".join(l for l in locs if l),
                "posted": parse_date(j.get("postedDate")),
                "url": "%s/job/%s" % (base, jid),
                "desc": clean(j.get("descriptionTeaser")),
                "_detail": ("phenom", base, jid),
            })
        offset += len(page)
        if not page or offset >= total:
            break
    return jobs, {"total": total}


def phenom_detail(http, base, jid):
    ddo = _phenom_ddo(http.get("%s/job/%s" % (base, jid)), "phenom detail %s" % jid)
    job = ((ddo.get("jobDetail") or {}).get("data") or {}).get("job") or {}
    return strip_html(job.get("description"))


# ---------------------------------------------------------------- SAP SuccessFactors career sites

SF_MAX_PAGES = 12
SF_ROW_RE = re.compile(r'<tr class="data-row[^"]*"[^>]*>(.*?)</tr>', re.S)
SF_LINK_RE = re.compile(r'<a\s([^>]*class="jobTitle-link"[^>]*)>(.*?)</a>', re.S)
SF_LOCATION_RE = re.compile(r'<span class="jobLocation">\s*([^<]*?)\s*</span>')
SF_DATE_RE = re.compile(r'<span class="jobDate">\s*([^<]*?)\s*</span>')
SF_TOTAL_RE = re.compile(r"Results <b>[^<]*</b> of <b>(\d+)</b>")


def successfactors(http, emp):
    """SuccessFactors career sites' HTML search. Searching for the country lists its jobs first,
    so paging stops at the first page without a UAE job (/services/ RSS is robots-disallowed)."""
    base = emp["base"].rstrip("/")
    root = "{0.scheme}://{0.netloc}".format(urlparse(base))
    jobs, start, total = [], 0, 0
    for _ in range(SF_MAX_PAGES):
        text = _page(http.get("%s/search/?q=&locationsearch=United%%20Arab%%20Emirates&startrow=%d"
                              % (base, start)), "successfactors %s" % emp["name"])
        m = SF_TOTAL_RE.search(text)
        total = int(m.group(1)) if m else 0
        rows = SF_ROW_RE.findall(text)
        uae = 0
        for row in rows:
            link = SF_LINK_RE.search(row)
            href = re.search(r'href="([^"]+)"', link.group(1)) if link else None
            loc = SF_LOCATION_RE.search(row)
            if not href or not loc or not UAE_RE.search(loc.group(1)):
                continue
            uae += 1
            date = SF_DATE_RE.search(row)
            url = urljoin(root, html.unescape(href.group(1)))
            jobs.append({
                "source": "successfactors:%s" % emp["name"],
                "source_type": "employer",
                "employer": emp["name"],
                "sector": emp.get("sector", ""),
                "title": strip_html(link.group(2)),
                "location": clean(loc.group(1)),
                "posted": parse_date(date.group(1)) if date else None,
                "url": url,
                "desc": "",
                "_detail": ("successfactors", url),
            })
        start += len(rows)
        if not rows or not uae or start >= total:
            break
    return jobs, {"total": total}


def successfactors_detail(http, url):
    text = _page(http.get(url), "successfactors detail")
    i = text.find('class="jobdescription"')
    if i < 0:
        return ""
    block = text[i:].split('<div class="clear', 1)[0]  # the description ends where the page footer starts
    return strip_html(re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", block, flags=re.S))


# ---------------------------------------------------------------- Jibe (iCIMS career sites)

def jibe(http, emp):
    """Jibe career sites serve their search as JSON at /api/jobs, 100 a page."""
    base = emp["base"].rstrip("/")
    if emp.get("crawl_delay"):
        http.set_gap(urlparse(base).netloc, emp["crawl_delay"])
    jobs, total = [], 0
    for page in range(1, 11):
        data = _json(http.get("%s/api/jobs?page=%d&limit=100" % (base, page)), "jibe %s" % emp["name"])
        total = data.get("totalCount") or 0
        rows = data.get("jobs") or []
        for row in rows:
            j = row.get("data") or row
            # most postings leave full_location empty; tags2 holds the city and tags3 the country
            loc = clean(j.get("full_location")) or ", ".join(
                clean(x) for x in (j.get("tags2") or []) + (j.get("tags3") or []) if clean(x))
            jobs.append({
                "source": "jibe:%s" % emp["name"],
                "source_type": "employer",
                "employer": emp["name"],
                "sector": emp.get("sector", ""),
                "title": clean(j.get("title")),
                "location": loc,
                "posted": parse_date(j.get("posted_date")),
                "url": "%s/jobs/%s" % (base, clean(j.get("slug"))),
                "desc": strip_html(" ".join(clean(j.get(k)) for k in
                                            ("description", "qualifications", "responsibilities"))),
            })
        if not rows or len(jobs) >= total:
            break
    return jobs, {"total": total}


# ---------------------------------------------------------------- startup ATS boards

def greenhouse(http, board):
    # EU-hosted boards are served by the same API host (boards-api.eu.greenhouse.io does not exist)
    data = _json(http.get("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % board["token"]),
                 "greenhouse %s" % board["token"])
    jobs = []
    for j in data.get("jobs") or []:
        locs = [clean((j.get("location") or {}).get("name"))]
        locs += [clean(o.get("location") or o.get("name")) for o in (j.get("offices") or [])]
        jobs.append(_board_job(board, "greenhouse", j.get("title"), locs,
                               j.get("first_published") or j.get("updated_at"),
                               j.get("absolute_url"), strip_html(j.get("content"))))
    return jobs, {"board_total": len(data.get("jobs") or [])}


def lever(http, board):
    host = "api.eu.lever.co" if board.get("region") == "eu" else "api.lever.co"
    data = _json(http.get("https://%s/v0/postings/%s?mode=json" % (host, board["token"])),
                 "lever %s" % board["token"])
    if isinstance(data, dict):
        raise NotFound("lever %s: %s" % (board["token"], data.get("error") or "not a board"))
    jobs = []
    for p in data:
        cats = p.get("categories") or {}
        locs = [clean(cats.get("location"))] + [clean(x) for x in (cats.get("allLocations") or [])]
        desc = " ".join([clean(p.get("descriptionPlain"))]
                        + [strip_html(l.get("content")) for l in (p.get("lists") or [])]
                        + [clean(p.get("additionalPlain"))])
        jobs.append(_board_job(board, "lever", p.get("text"), locs, p.get("createdAt"),
                               p.get("hostedUrl"), desc))
    return jobs, {"board_total": len(data)}


def ashby(http, board):
    data = _json(http.get("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true"
                          % quote(board["token"])), "ashby %s" % board["token"])
    jobs = []
    for j in data.get("jobs") or []:
        if j.get("isListed") is False:
            continue
        locs = [clean(j.get("location"))]
        locs += [clean(s.get("location")) for s in (j.get("secondaryLocations") or [])]
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        locs.append(" ".join(clean(addr.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")))
        desc = clean(j.get("descriptionPlain")) or strip_html(j.get("descriptionHtml"))
        jobs.append(_board_job(board, "ashby", j.get("title"), locs, j.get("publishedAt"),
                               j.get("jobUrl"), desc))
    return jobs, {"board_total": len(data.get("jobs") or [])}


def workable(http, board):
    data = _json(http.get("https://apply.workable.com/api/v1/widget/accounts/%s?details=true"
                          % board["token"]), "workable %s" % board["token"])
    jobs = []
    for j in data.get("jobs") or []:
        locs = [", ".join(clean(j.get(k)) for k in ("city", "state", "country") if j.get(k))]
        for l in j.get("locations") or []:
            locs.append(", ".join(clean(l.get(k)) for k in ("city", "region", "country") if l.get(k)))
        desc = strip_html(j.get("description")) + " " + clean(j.get("experience"))
        jobs.append(_board_job(board, "workable", j.get("title"), locs,
                               j.get("published_on") or j.get("created_at"),
                               j.get("url") or j.get("shortlink") or j.get("application_url"), desc))
    if data.get("name") and not board.get("name"):
        for job in jobs:
            job["employer"] = data["name"]
    return jobs, {"board_total": len(data.get("jobs") or [])}


def pinpoint(http, board):
    data = _json(http.get("https://%s.pinpointhq.com/jobs.json" % board["token"]), "pinpoint %s" % board["token"])
    jobs = []
    for j in data.get("data") or []:
        desc = strip_html(" ".join(clean(j.get(k)) for k in (
            "description", "key_responsibilities", "skills_knowledge_expertise")))
        jobs.append(_board_job(board, "pinpoint", j.get("title"), [clean((j.get("location") or {}).get("name"))],
                               None, j.get("url"), desc))
    return jobs, {"board_total": len(data.get("data") or [])}


TT = "{https://teamtailor.com/locations}"


def teamtailor(http, board):
    """Teamtailor career sites publish their open jobs as RSS at /jobs.rss. The token is the
    site's host, or the company's teamtailor.com subdomain."""
    host = board["token"] if "." in board["token"] else "%s.teamtailor.com" % board["token"]
    text = _page(http.get("https://%s/jobs.rss" % host), "teamtailor %s" % board["token"])
    try:
        channel = ElementTree.fromstring(text.encode("utf-8")).find("channel")
    except ElementTree.ParseError:
        raise SourceError("teamtailor %s: not RSS" % board["token"])
    jobs = []
    for item in channel.findall("item") if channel is not None else []:
        locs = [", ".join(clean(loc.findtext(TT + k)) for k in ("city", "country") if loc.findtext(TT + k))
                for loc in item.iter(TT + "location")]
        jobs.append(_board_job(board, "teamtailor", item.findtext("title"), locs, item.findtext("pubDate"),
                               item.findtext("link"), strip_html(item.findtext("description"))))
    return jobs, {"board_total": len(jobs)}


def _board_job(board, ats, title, locs, posted, url, desc):
    return {
        "source": "%s:%s" % (ats, board["token"]),
        "source_type": "ats",
        "employer": board.get("name") or board["token"],
        "sector": board.get("sector", "tech"),
        "title": clean(title),
        "location": "; ".join(l for l in locs if l),
        "posted": parse_date(posted),
        "url": clean(url),
        "desc": desc,
    }


BOARD_FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable,
                  "pinpoint": pinpoint, "teamtailor": teamtailor}


# ---------------------------------------------------------------- Amazon

def amazon(http):
    jobs = []
    for offset in range(0, 400, 100):
        # loc_query does not filter (it returns all 10,000 jobs worldwide); the country code does
        url = ("https://www.amazon.jobs/en/search.json?offset=%d&result_limit=100&sort=recent"
               "&normalized_country_code%%5B%%5D=ARE" % offset)
        data = _json(http.get(url), "amazon")
        page = data.get("jobs") or []
        for j in page:
            loc = clean(j.get("normalized_location")) or clean(j.get("location"))
            desc = strip_html(" ".join(clean(j.get(k)) for k in (
                "description_short", "basic_qualifications", "preferred_qualifications")))
            jobs.append({
                "source": "amazon", "source_type": "employer",
                "employer": clean(j.get("company_name")) or "Amazon", "sector": "big tech",
                "title": clean(j.get("title")), "location": loc,
                "posted": parse_date(j.get("posted_date")),
                "url": "https://www.amazon.jobs" + clean(j.get("job_path")),
                "desc": desc,
            })
        if len(page) < 100:
            break
    return jobs, {}


# ---------------------------------------------------------------- JobSpy (LinkedIn, Indeed, Google, Bayt)

BLOCKED_RE = re.compile(r"\b(403|429)\b|blocked|captcha|too many requests", re.I)


class _LogCapture(logging.Handler):
    """Collects what a JobSpy scraper logs. A blocked or failed query comes back as an empty
    result, and the log is the only place that says why."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def jobspy_site(site, queries, log):
    """Runs one site's queries one at a time with pauses. Returns (jobs, meta)."""
    from jobspy import scrape_jobs  # imported lazily: heavy, and only used on full runs

    capture = _LogCapture()
    logger = logging.getLogger("jobspy.%s" % site)
    logger.addHandler(capture)
    jobs, errors, ok, blocked = [], [], 0, 0
    for q in queries:
        kw = {"site_name": [site], "search_term": q, "verbose": 0}
        if site == "indeed":
            kw.update(location="United Arab Emirates", country_indeed="united arab emirates",
                      hours_old=72, results_wanted=40)
        elif site == "linkedin":
            kw.update(location="United Arab Emirates", hours_old=72, results_wanted=25)
        elif site == "google":
            kw.update(google_search_term="%s jobs in United Arab Emirates since yesterday" % q,
                      results_wanted=20)
        elif site == "bayt":
            kw.update(location="UAE", hours_old=72, results_wanted=25)
        del capture.messages[:]
        try:
            rows = scrape_jobs(**kw).to_dict("records")
            if any(BLOCKED_RE.search(m) for m in capture.messages):
                blocked += 1  # possibly part way through: a later page was refused
            if capture.messages:
                errors.append("%s: %s" % (q, capture.messages[0][:160]))
            if rows or not capture.messages:
                ok += 1
            for row in rows:
                url = clean(row.get("job_url"))
                jobs.append({
                    "source": "jobspy:%s" % site,
                    "source_type": site,
                    "employer": clean(row.get("company")),
                    "sector": "",
                    "title": clean(row.get("title")),
                    "location": clean(row.get("location")),
                    "posted": parse_date(row.get("date_posted")),
                    "url": url,
                    "url_direct": clean(row.get("job_url_direct")),
                    "desc": clean(row.get("description"))[:6000],
                })
        except Exception as e:  # one failing query must not stop the rest
            errors.append("%s: %s" % (q, str(e)[:160]))
            log("  jobspy %s '%s' failed: %s" % (site, q, str(e)[:160]))
        time.sleep(random.uniform(4, 8))
    logger.removeHandler(capture)
    return jobs, {"queries": len(queries), "queries_ok": ok, "blocked": blocked, "errors": errors[:5]}
