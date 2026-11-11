"""End-to-end run against canned API responses (no network). Run: python -m tests.test_offline_run"""
import json
import logging
import os
from datetime import date
import random
import shutil
import sys
import tempfile
import types

import run
from engine import http as http_mod
from engine import sources
from engine import util

TODAY = date(2026, 11, 10)  # the day the fixtures were written: frozen, so their dates never age out

FAILING = set()  # board tokens that answer 404, to exercise carry-over
SCRAPES = {"linkedin": 0, "bayt": 0}  # JobSpy calls per site, to check that a blocked site is left alone
LINKEDIN = {"open": False}  # False: LinkedIn refuses every search. True: it answers, without descriptions
LI_ROWS = [(9001, "Gulf Bank", "Graduate Data Analyst Programme"), (9002, "Acme AI", "Junior Data Scientist"),
           (9003, "ADIB - Abu Dhabi Islamic Bank", "MIS Analyst"),  # Oracle's job 105, nationals only
           (9004, "Ziina", "Junior Python Developer"),  # on Ashby, with a description
           (9005, "OldCo", "Data Engineer Trainee"),  # seen on an earlier day
           (9006, "Acme Robotics", "Junior AI Engineer"), (9007, "Beta Labs", "Junior BI Developer"),
           (9008, "Emirates", "Business Insights Analyst - Emiratization Graduate Programme")]  # the title decides
LI_PAGES = {"9001": (200, "/jobs/view/9001", "Join our graduate programme. This programme is open to UAE Nationals only."),
            "9002": (200, "/jobs/view/9002", "About the job. 0-1 years of experience with Python. Fresh graduates welcome."),
            "9006": (429, "/jobs/view/9006", "")}
LI_ASKED = []  # LinkedIn job pages requested, in order


class FakeLinkedIn:
    """Stands in for JobSpy's LinkedIn scraper: like its _fetch_details, it reads the page through
    self.session.get and returns {} when the page is refused or redirected."""

    def __init__(self):
        self.session = types.SimpleNamespace(get=self.answer)

    @staticmethod
    def answer(url, **kw):
        jid = url.rsplit("/", 1)[1]
        LI_ASKED.append(jid)
        status, path, text = LI_PAGES.get(jid, (200, "/jobs/view/" + jid, "A good role."))
        return types.SimpleNamespace(status_code=status, url="https://www.linkedin.com" + path, text=text)

    def _fetch_details(self, jid):
        resp = self.session.get("https://www.linkedin.com/jobs/view/%s" % jid)
        if resp.status_code != 200 or "/jobs/view/" not in resp.url:
            return {}
        return {"description": resp.text}


class FakeFrame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        return self.rows


def fake_scrape_jobs(site_name, search_term, **kw):
    """Stands in for jobspy.scrape_jobs: LinkedIn is 'blocked'. Bayt returns a UAE job, plus
    Ziina's Ashby job again under another employer spelling and word order."""
    site = site_name[0]
    SCRAPES[site] += 1
    if site == "linkedin":
        if not LINKEDIN["open"]:
            logging.getLogger("jobspy.linkedin").error("response status code 429 (blocked: use a proxy)")
            return FakeFrame([])
        return FakeFrame([{"job_url": "https://www.linkedin.com/jobs/view/%d" % n, "company": company, "title": title,
                           "location": "Dubai, United Arab Emirates", "date_posted": run.today_dubai(),
                           "description": None} for n, company, title in LI_ROWS] if search_term == "data analyst" else [])
    assert kw.get("location") == "UAE", kw  # Bayt must be asked for the UAE, not every country
    return FakeFrame([{"job_url": "https://www.bayt.com/en/uae/jobs/data-analyst-1/", "company": "Acme Recruitment",
                       "title": "Junior Data Analyst", "location": "Dubai, UAE", "date_posted": run.today_dubai(),
                       "description": "1-2 years of experience with SQL"},
                      {"job_url": "https://www.bayt.com/en/uae/jobs/python-developer-2/", "company": "Ziina Technologies",
                       "title": "Python Developer - Junior", "location": "Abu Dhabi, UAE",
                       "date_posted": run.today_dubai(), "description": ""}])


class FakeResp:
    def __init__(self, payload, status=200, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._payload


PHENOM_JOBS = [
    {"jobId": "77", "title": "Junior BI Analyst", "location": "Abu Dhabi, United Arab Emirates",
     "postedDate": "2026-10-30T06:44:10.000+0000", "descriptionTeaser": "Build Power BI reports"},
    {"jobId": "78", "title": "Reporting Analyst", "location": "Dubai, United Arab Emirates",
     "postedDate": "2026-10-30T06:44:10.000+0000", "descriptionTeaser": "Reporting"}]
PHENOM_DETAIL = {"77": "<p>0-1 years of experience with SQL</p>",
                 "78": "<p>Reporting Analyst (For UAEN applicants) Embark on a journey</p>"}
SF_SEARCH = ('<span class="paginationLabel">Results <b>1 – 2</b> of <b>2</b></span><table>'
             '<tr class="data-row"><td><span class="jobTitle hidden-phone"><a href="/job/Dubai-AI-Engineer/123/" '
             'class="jobTitle-link">AI Engineer - Graduate</a></span></td><td class="colLocation">'
             '<span class="jobLocation"> Dubai, AE </span></td><td><span class="jobDate">Oct 28, 2026 </span></td></tr>'
             '<tr class="data-row"><td><a class="jobTitle-link" href="/job/London-Analyst/124/">Data Analyst, London</a>'
             '</td><td><span class="jobLocation"> London, GB </span></td></tr></table>')
SF_DETAIL = ('<span class="jobdescription"><p>Fresh graduates welcome.</p><style>p {margin: 0}</style></span>'
             '</div><div class="clear"></div><footer>Our partners bring 10 years of experience</footer>')
TT_RSS = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:tt="https://teamtailor.com/locations">'
          '<channel><title>TT</title><item><title>Junior Analytics Engineer</title>'
          '<description>&lt;p&gt;Fresh graduates&lt;/p&gt;</description>'
          '<pubDate>Mon, 02 Nov 2026 12:05:49 +0400</pubDate>'
          '<link>https://careers.example-tt.com/jobs/1-junior-analytics-engineer</link>'
          '<tt:locations><tt:location><tt:city>Dubai</tt:city><tt:country>United Arab Emirates</tt:country>'
          '</tt:location></tt:locations></item></channel></rss>')


AV_LIST = ('<p>2 results</p><div class="results">' + "".join(
    '<article class="article article--result %d" id="article--%d"><h3><a class="link" '
    'href="https://example-avature.net/en_US/portal/JobDetail/%s/%d" data-au="x"> %s </a></h3>'
    '<span class="paragraph paragraph--inline"> · </span><span class="paragraph paragraph--inline"> Holding Co '
    '</span><span class="paragraph paragraph--inline"> Technology </span><span class="paragraph paragraph--inline">'
    ' 09-Oct-2026 </span></article>' % (n, n, slug, n, title)
    for n, slug, title in ((11, "Graduate-Data-Analyst", "Graduate Data Analyst"),
                           (12, "Junior-BI-Developer", "Junior BI Developer"))) + "</div>")
AV_DETAIL = ('<div class="article__content__view"><div class="article__content__view__field ">'
             '<div class="article__content__view__field__label" > Location </div>'
             '<div class="article__content__view__field__value"> %s </div></div>'
             '<div class="article__content__view__field__value"><p>Fresh graduates welcome.</p></div></div>')
ATTRAX_PAGE = "".join(
    '<div class="attrax-vacancy-tile sector-x" data-jobid="%s"><a class="attrax-vacancy-tile__title '
    'attrax-button" href="/job/%s-jid-%s">%s</a><div class="attrax-vacancy-tile__location-freetext">'
    '<p class="attrax-vacancy-tile__item-label"> Location </p><p class="attrax-vacancy-tile__item-value"> %s </p>'
    '</div><div><p class="attrax-vacancy-tile__item-label"> Description </p>'
    '<p class="attrax-vacancy-tile__item-value"> Entry level role </p></div></div>' % (jid, slug, jid, title, loc)
    for jid, slug, title, loc in (("501", "junior-analyst", "Junior Analyst, Logistics Performance", "Dubai, UAE"),
                                  ("502", "category-manager", "Category Manager", "Muscat, Oman")))
DERIV_JOBS = [
    {"id": "d1", "title": "Junior Python Engineer", "status": "open", "location": "Dubai, United Arab Emirates",
     "locations": [{"location": "Dubai, United Arab Emirates"}], "description": "## About\n0-2 years of experience",
     "requirements": None, "created_at": None},
    {"id": "d2", "title": "Applied AI Engineer", "status": "open", "location": "Cyberjaya, Malaysia",
     "locations": [{"location": "Cyberjaya, Malaysia"}], "description": "", "requirements": None}]


def fake_request(self, method, url, retries=2, **kw):
    self.calls += 1
    if "example-avature.net" in url:
        if "/SearchJobs/" in url:
            return FakeResp(None, text=AV_LIST if "jobOffset=0" in url else "<p>2 results</p>")
        return FakeResp(None, text=AV_DETAIL % ("United Kingdom" if url.endswith("/12") else "United Arab Emirates"))
    if "example-attrax.com" in url:
        return FakeResp(None, text=ATTRAX_PAGE)  # every page repeats the same tiles: paging must stop
    if "join.deriv.careers/api/job-openings" in url:
        return FakeResp(DERIV_JOBS)
    if "example-phenom.com" in url:
        if "/search-results" in url:
            ddo = {"eagerLoadRefineSearch": {"status": 200, "totalHits": 2, "data": {"jobs": PHENOM_JOBS}}}
        else:
            ddo = {"jobDetail": {"data": {"job": {"description": PHENOM_DETAIL[url.rsplit("/", 1)[1]]}}}}
        return FakeResp(None, text="<script>phApp.ddo = %s; phApp.sessionParams = {};</script>" % json.dumps(ddo))
    if "example-sf.com" in url:
        return FakeResp(None, text=SF_SEARCH if "/search/" in url else SF_DETAIL)
    if "example-jibe.com/api/jobs" in url:
        return FakeResp({"totalCount": 1, "jobs": [{"data": {
            "slug": "9", "title": "IT Support Specialist", "full_location": "", "tags2": ["Abu Dhabi"],
            "tags3": ["United Arab Emirates"], "posted_date": "2026-11-01T12:20:00+0000",
            "description": "<p>Support users</p>", "qualifications": "<p>1 year of experience</p>"}}]})
    if "pinpointhq.com/jobs.json" in url:
        if "//tabbyx." not in url:
            return FakeResp({}, 404)
        return FakeResp({"data": [
            {"title": "Data Scientist II", "location": {"name": "UAE"}, "url": "https://tabbyx.pinpointhq.com/en/jobs/1",
             "description": "<p>2 years of experience</p>"},
            {"title": "Data Analyst", "location": {"name": "KSA"}, "url": "https://tabbyx.pinpointhq.com/en/jobs/2"}]})
    if url.endswith("/jobs.rss"):
        if "example-tt.com" not in url:
            return FakeResp(None, 404, text="not found")
        return FakeResp(None, text=TT_RSS)
    if "recruitingCESites" in url:
        return FakeResp({"items": [{"SiteNumber": "CX_1", "SiteName": "Careers", "StatusCode": "ORA_ACTIVE"},
                                   {"SiteNumber": "CX", "SiteName": "Old", "StatusCode": "ORA_INACTIVE"}]})
    if "recruitingCEJobRequisitionDetails" in url:
        jid = url.split("Id=%22")[1].split("%22")[0]
        text = {"101": "<p>0-2 years of experience in HR analytics</p>",
                "104": "<p>Minimum 6 years of experience</p>",
                "105": "<p>This role is open to UAE Nationals only.</p>"}.get(jid, "<p>Good role</p>")
        return FakeResp({"items": [{"ExternalQualificationsStr": text}]})
    if "recruitingCEJobRequisitions" in url:
        if "offset=0" not in url:
            return FakeResp({"items": [{"TotalJobsCount": 5, "requisitionList": []}]})
        reqs = [
            {"Id": "101", "Title": "HR Data Analyst", "PostedDate": "2026-10-22",
             "PrimaryLocation": "Abu Dhabi, Abu Dhabi, United Arab Emirates", "ShortDescriptionStr": "HR data"},
            {"Id": "102", "Title": "Senior Data Engineer", "PostedDate": "2026-10-20",
             "PrimaryLocation": "Dubai, United Arab Emirates"},
            {"Id": "103", "Title": "Data Analyst", "PostedDate": "2026-10-20",
             "PrimaryLocation": "Cairo, Egypt"},
            {"Id": "104", "Title": "Data Scientist", "PostedDate": "2026-10-25",
             "PrimaryLocation": "Dubai, United Arab Emirates"},
            {"Id": "105", "Title": "MIS Analyst", "PostedDate": "2026-10-26",
             "PrimaryLocation": "Dubai, United Arab Emirates"},
        ]
        return FakeResp({"items": [{"TotalJobsCount": 5, "requisitionList": reqs}]})
    if "/wday/cxs/fallbackco/" in url and method == "POST":
        # a tenant whose UAE facet finds nothing when applied (Baker Hughes): the text search is used
        body = kw.get("json") or {}
        if body.get("appliedFacets"):
            return FakeResp({"total": 0, "jobPostings": []})
        if body.get("searchText") == "United Arab Emirates":
            return FakeResp({"total": 2, "jobPostings": [
                {"title": "Junior Data Engineer, Text Search", "externalPath": "/job/AE-DUBAI/Junior-DE_R-9",
                 "locationsText": "AE-DUBAI-TECHNO PARK", "postedOn": "Posted 3 Days Ago"},
                {"title": "Data Analyst", "externalPath": "/job/x/Data-Analyst_R-10",
                 "locationsText": "2 Locations", "postedOn": "Posted Today"}]})  # nothing says this one is UAE
        return FakeResp({"total": 600, "jobPostings": [], "facets": [
            {"facetParameter": "locationMainGroup", "values": [
                {"facetParameter": "locationHierarchy1", "descriptor": "Country", "values": [
                    {"descriptor": "Dubai", "id": "h1", "count": 2}]}]}]})
    if "/wday/cxs/" in url and method == "POST":
        body = kw.get("json") or {}
        if not body.get("appliedFacets"):
            return FakeResp({"total": 900, "jobPostings": [], "facets": [
                {"facetParameter": "locationMainGroup", "values": [
                    {"facetParameter": "locations", "values": [
                        {"descriptor": "Dubai, United Arab Emirates", "id": "loc1", "count": 2},
                        {"descriptor": "London, UK", "id": "loc2", "count": 50}]}]}]})
        assert body["appliedFacets"] == {"locations": ["loc1"]}, body
        return FakeResp({"total": 3, "jobPostings": [
            {"title": "Associate Analyst, Data & Services", "externalPath": "/job/Dubai/Associate-Analyst_R-1",
             "locationsText": "Dubai, United Arab Emirates", "postedOn": "Posted 2 Days Ago"},
            {"title": "Director, Product", "externalPath": "/job/Dubai/Director_R-2",
             "locationsText": "Dubai, United Arab Emirates", "postedOn": "Posted Today"},
            {"title": "Junior Data Engineer", "externalPath": "/job/Dubai/Junior-Data-Engineer_R-3",
             "locationsText": "2 Locations", "postedOn": "Posted Yesterday"}]})
    if "/wday/cxs/" in url:
        return FakeResp({"jobPostingInfo": {"jobDescription": "<p>1+ years of experience with SQL</p>"}})
    if "boards-api" in url:
        if "/boards/careem/" not in url or "careem" in FAILING:
            return FakeResp({"error": "not found"}, 404)
        return FakeResp({"jobs": [
            {"id": 1, "title": "Data Scientist", "location": {"name": "Dubai, United Arab Emirates"},
             "absolute_url": "https://boards.greenhouse.io/careem/jobs/1", "first_published": "2026-10-30T09:00:00Z",
             "content": "&lt;p&gt;2+ years of experience with Python&lt;/p&gt;"},
            {"id": 2, "title": "Backend Engineer", "location": {"name": "Berlin, Germany"},
             "absolute_url": "https://boards.greenhouse.io/careem/jobs/2", "content": ""}]})
    if "api.lever.co" in url:
        if "/postings/aldar" not in url:
            return FakeResp({"ok": False, "error": "Document not found"}, 404)
        return FakeResp([{"text": "Graduate Programme - Data & Technology", "hostedUrl": "https://jobs.lever.co/aldar/abc",
                          "createdAt": 1793000000000, "categories": {"location": "Abu Dhabi"},
                          "descriptionPlain": "For recent graduates. Company visa provided."}])
    if "api.ashbyhq.com" in url:
        if "/job-board/ziina" not in url:
            return FakeResp({}, 404)
        return FakeResp({"jobs": [{"title": "Junior Python Developer", "location": "Dubai", "isListed": True,
                                   "publishedAt": "2026-10-31T10:00:00Z", "jobUrl": "https://jobs.ashbyhq.com/ziina/1",
                                   "descriptionPlain": "1-2 years of experience. Candidates on own visa preferred."}]})
    if "apply.workable.com" in url:
        if "/accounts/bayutdubizzle" not in url:
            return FakeResp({}, 404)
        return FakeResp({"name": "dubizzle Group", "jobs": [
            {"title": "Data Analyst", "city": "Dubai", "country": "United Arab Emirates",
             "url": "https://apply.workable.com/bayutdubizzle/j/ABC/", "published_on": "2026-10-28",
             "description": "<p>2 years of experience</p>"},
            {"title": "Backend Developer", "city": "Dubai", "country": "United Arab Emirates",  # a 2023 ad
             "url": "https://apply.workable.com/bayutdubizzle/j/OLD/", "published_on": "2023-09-05",
             "description": "<p>1 year of experience</p>"}]})
    if "amazon.jobs" in url:
        assert "normalized_country_code" in url, url
        return FakeResp({"hits": 1, "jobs": [
            {"title": "Business Intelligence Engineer", "normalized_location": "Dubai, ARE",
             "job_path": "/en/jobs/123/bie", "posted_date": "October 29, 2026",
             "basic_qualifications": "3+ years of experience in analytics"}]})
    return FakeResp({}, 404)


def main():
    tmp = tempfile.mkdtemp()
    try:
        run.DATA = os.path.join(tmp, "data")
        os.makedirs(run.DATA)
        cfg = {
            "oracle": [{"name": "ADIB", "sector": "banking", "host": "x.oraclecloud.com", "sites": ["CX_1"]},
                       {"name": "NoSites", "host": "y.oraclecloud.com", "sites": []}],
            "workday": [{"name": "Mastercard", "sector": "payments", "tenant": "mastercard", "wd": "wd1",
                         "site": "CorporateCareers"},
                        {"name": "FallbackCo", "tenant": "fallbackco", "wd": "wd5", "site": "Careers"}],
            "phenom": [{"name": "PhenomCo", "base": "https://careers.example-phenom.com/global/en"}],
            "successfactors": [{"name": "SFCo", "base": "https://careers.example-sf.com"}],
            "jibe": [{"name": "JibeCo", "base": "https://careers.example-jibe.com", "crawl_delay": 5}],
            "avature": [{"name": "AvCo", "base": "https://example-avature.net/en_US/portal",
                         "assume_location": "United Arab Emirates"}],
            "attrax": [{"name": "AtCo", "base": "https://careers.example-attrax.com/co-jobs"}],
            "deriv": True,
            "boards": [{"ats": "greenhouse", "token": "careem", "name": "Careem"},
                       {"ats": "lever", "token": "aldar", "name": "Aldar"},
                       {"ats": "ashby", "token": "ziina", "name": "Ziina"},
                       {"ats": "workable", "token": "bayutdubizzle"},
                       {"ats": "pinpoint", "token": "tabbyx", "name": "TabbyX"},
                       {"ats": "teamtailor", "token": "careers.example-tt.com", "name": "TTCo"}],
            "amazon": True,
            "probe": ["nosuchco"],
        }
        search = {"jobspy": {"linkedin": ["data analyst", "data scientist", "data engineer"], "bayt": ["data analyst"]}}
        run.load_yaml = lambda name: cfg if name == "employers.yaml" else search
        run.today_dubai = util.today_dubai = lambda: TODAY
        http_mod.Http.request = fake_request
        sys.modules["jobspy"] = types.ModuleType("jobspy")
        sys.modules["jobspy"].scrape_jobs = fake_scrape_jobs
        sources._linkedin_scraper = FakeLinkedIn
        random.uniform = lambda a, b: 0  # no pauses between the fake JobSpy queries
        os.environ["FULL_RUN"] = "1"  # exercises the probe and JobSpy
        run.main()

        latest = json.load(open(os.path.join(run.DATA, "latest.json")))
        titles = {j["title"]: j for j in latest["jobs"]}
        print("\nkept:", sorted(titles))
        print("rejected:", latest["summary"]["rejected"])
        expect_kept = {"HR Data Analyst", "Associate Analyst, Data & Services", "Data Scientist",
                       "Graduate Programme - Data & Technology", "Junior Python Developer", "Data Analyst",
                       "Business Intelligence Engineer", "Junior Data Engineer", "Junior Data Analyst",
                       "Junior BI Analyst", "AI Engineer - Graduate", "IT Support Specialist", "Data Scientist II",
                       "Junior Analytics Engineer", "Graduate Data Analyst", "Junior Analyst, Logistics Performance",
                       "Junior Python Engineer", "Junior Data Engineer, Text Search"}
        assert set(titles) == expect_kept, set(titles) ^ expect_kept
        # Avature: the job page gave the location; the candidate whose page says United Kingdom is out
        assert titles["Graduate Data Analyst"]["location"] == "United Arab Emirates"
        assert titles["Graduate Data Analyst"]["posted"] == "2026-10-09"
        assert latest["summary"]["rejected"].get("not-uae") == 1
        # a 2023 employer ad is dropped as stale; the live one from the same board stays
        assert latest["summary"]["rejected"].get("stale") == 1
        # a tenant whose UAE facet finds nothing is asked by text; only postings that say UAE are kept
        assert titles["Junior Data Engineer, Text Search"]["location"] == "AE-DUBAI-TECHNO PARK"
        assert titles["Junior Data Engineer, Text Search"]["city"] == "Dubai"
        health0 = json.load(open(os.path.join(run.DATA, "health.json")))["sources"]
        assert health0["workday:FallbackCo"]["fetched"] == 1 and health0["workday:FallbackCo"]["meta"]["by_text"]
        assert not health0["workday:Mastercard"]["meta"].get("by_text")
        # a 32-day-old posting is kept, ranked a point lower than the same posting would be fresh:
        # data analyst 3.0 + junior 1.2 + new 1.0 - older than 30 days 1.0 + employer 0.6
        assert titles["Graduate Data Analyst"]["age_days"] == 32
        assert titles["Graduate Data Analyst"]["score"] == 4.8, titles["Graduate Data Analyst"]["score"]
        # agency flag: the Bayt poster is a recruitment agency
        assert "agency" in titles["Junior Data Analyst"]["flags"], titles["Junior Data Analyst"]
        assert "agency" not in titles["HR Data Analyst"]["flags"]
        assert titles["Junior Analyst, Logistics Performance"]["url"] == \
            "https://careers.example-attrax.com/job/junior-analyst-jid-501"
        assert titles["Junior Python Engineer"]["url"] == "https://join.deriv.careers/jobs/d1"
        # new collectors: links, dates and locations come through
        assert titles["Junior BI Analyst"]["url"] == "https://careers.example-phenom.com/global/en/job/77"
        assert titles["AI Engineer - Graduate"]["url"] == "https://careers.example-sf.com/job/Dubai-AI-Engineer/123/"
        assert titles["AI Engineer - Graduate"]["posted"] == "2026-10-28"
        assert titles["AI Engineer - Graduate"]["min_years"] is None  # the page footer is not description
        assert titles["IT Support Specialist"]["location"] == "Abu Dhabi, United Arab Emirates"
        assert titles["Junior Analytics Engineer"]["posted"] == "2026-11-02"
        assert "stretch_3y" in titles["Business Intelligence Engineer"]["flags"]
        assert "own_visa_preferred" in titles["Junior Python Developer"]["flags"]
        assert titles["HR Data Analyst"]["url"].endswith("/sites/CX_1/job/101")
        # a Workday posting listed as "2 Locations" is kept under the UAE facet it came from
        assert titles["Junior Data Engineer"]["location"] == "2 Locations; Dubai, United Arab Emirates"
        assert latest["summary"]["rejected"].get("nationals-only") == 2  # ADIB 105 and Phenom 78
        assert latest["summary"]["rejected"].get("4+ years") == 1
        assert os.path.exists(os.path.join(run.DATA, "latest.md"))
        cache = json.load(open(os.path.join(run.DATA, "detail_cache.json")))
        assert len(cache) >= 4
        health = json.load(open(os.path.join(run.DATA, "health.json")))["sources"]
        # an Oracle entry without sites fails and names the active sites instead of guessing one
        assert not health["oracle:NoSites"]["ok"] and "CX_1 (Careers)" in health["oracle:NoSites"]["error"]
        assert "CX (Old)" not in health["oracle:NoSites"]["error"]
        # a blocked JobSpy site is recorded as blocked, not as an ok run with no jobs, and after two
        # blocks in a row its third query is never sent
        assert not health["jobspy:linkedin"]["ok"] and health["jobspy:linkedin"]["blocked"] == 2
        assert health["jobspy:linkedin"]["meta"]["skipped"] == 1 and SCRAPES["linkedin"] == 2, SCRAPES
        # the same job on Ashby and Bayt (another employer spelling, other word order, other city) is one
        # row, with the employer's own link
        ziina = titles["Junior Python Developer"]
        assert ziina["seen_on"] == ["ashby:ziina", "jobspy:bayt"] and ziina["url"].startswith("https://jobs.ashbyhq.com")
        md = open(os.path.join(run.DATA, "latest.md"), encoding="utf-8").read()
        assert "## Status" in md and "ashby + bayt" in md
        status = latest["summary"]["status"]
        assert "oracle:NoSites" in status["failing"] and "jobspy:linkedin" in status["blocked"], status
        assert status["new_last_7_days"]["employer"] + status["new_last_7_days"]["jobspy"] == len(titles)
        assert health["jobspy:bayt"]["ok"] and health["jobspy:bayt"]["fetched"] == 2
        assert health["attrax:AtCo"]["meta"]["pages"] == 2, health["attrax:AtCo"]  # page 2 had nothing new
        sample = json.load(open(os.path.join(run.DATA, "rejected_sample.json")))
        assert {"senior", "nationals-only", "4+ years"} <= {x["reason"] for x in sample}

        # second run the same day: details come from the cache; first_seen is kept
        run.main()
        latest2 = json.load(open(os.path.join(run.DATA, "latest.json")))
        assert {j["title"] for j in latest2["jobs"]} == expect_kept
        assert all(j["first_seen"] == latest["jobs"][0]["first_seen"] for j in latest2["jobs"])
        health = json.load(open(os.path.join(run.DATA, "health.json")))["sources"]
        assert health["_details"]["fetched"] == 0, health["_details"]

        # facts cached under older description patterns are stale: those details are fetched again
        cache_path = os.path.join(run.DATA, "detail_cache.json")
        with open(cache_path) as fh:
            cache = json.load(fh)
        for facts in cache.values():
            facts["v"] = "old"
        with open(cache_path, "w") as fh:
            json.dump(cache, fh)
        run.main()
        health = json.load(open(os.path.join(run.DATA, "health.json")))["sources"]
        assert health["_details"]["fetched"] == 11, health["_details"]  # every candidate with a detail page

        # midday run: JobSpy is skipped and one board fails; their jobs are carried and stay new today.
        # A carried row must still pass today's rules: a Bayt row with a title the filters now exclude
        # (planted in latest.json as if an older run had kept it) is not carried
        latest_path = os.path.join(run.DATA, "latest.json")
        with open(latest_path) as fh:
            planted = json.load(fh)
        planted["jobs"].append(dict(titles["Junior Data Analyst"], key="planted", title="Quality Control Analyst",
                                    url="https://www.bayt.com/en/uae/jobs/qc-analyst-3/"))
        with open(latest_path, "w") as fh:
            json.dump(planted, fh)
        FAILING.add("careem")
        os.environ["FULL_RUN"] = "0"
        run.main()
        latest3 = json.load(open(os.path.join(run.DATA, "latest.json")))
        titles3 = {j["title"]: j for j in latest3["jobs"]}
        assert set(titles3) == expect_kept, set(titles3) ^ expect_kept
        assert latest3["summary"]["carried_over"] == 2
        assert titles3["Junior Data Analyst"]["is_new"] and titles3["Data Scientist"]["is_new"]
        assert "agency" in titles3["Junior Data Analyst"]["flags"]  # flags refreshed on a carried row
        # failures in a row are counted across runs; LinkedIn did not run this time and keeps its count
        stuck = latest3["summary"]["status"]["failing_in_a_row"]
        assert stuck == {"oracle:NoSites": 4, "jobspy:linkedin": 3}, stuck

        # history saved under an older key: known jobs must not come back as new
        seen_path = os.path.join(run.DATA, "seen.json")
        with open(seen_path) as fh:
            seen = json.load(fh)
        legacy = {"legacy-%d" % n: dict(v, first_seen="2026-10-01") for n, v in enumerate(seen.values())}
        with open(seen_path, "w") as fh:
            json.dump(legacy, fh)
        FAILING.discard("careem")
        os.environ["FULL_RUN"] = "1"
        run.main()
        latest4 = json.load(open(os.path.join(run.DATA, "latest.json")))
        assert {j["title"] for j in latest4["jobs"]} == expect_kept
        assert not any(j["is_new"] for j in latest4["jobs"]), [j["title"] for j in latest4["jobs"] if j["is_new"]]
        assert all(j["first_seen"] == "2026-10-01" for j in latest4["jobs"])

        # LinkedIn answers again, without descriptions. The page of each role new today is read, one at
        # a time, until the first refusal; not for jobs seen on an earlier day or described elsewhere
        with open(seen_path) as fh:
            seen = json.load(fh)
        seen["oldco"] = {"first_seen": "2026-10-01", "last_seen": str(run.today_dubai()),
                         "title": "Data Engineer Trainee", "employer": "OldCo"}
        with open(seen_path, "w") as fh:
            json.dump(seen, fh)
        LINKEDIN["open"] = True
        search["linkedin_pages"] = 20
        run.main()
        latest5 = json.load(open(os.path.join(run.DATA, "latest.json")))
        titles5 = {j["title"]: j for j in latest5["jobs"]}
        pages = latest5["summary"]["status"]["linkedin_pages"]
        print("linkedin pages:", pages, LI_ASKED)
        assert LI_ASKED[-1] == "9006" and not {"9003", "9004", "9005", "9008"} & set(LI_ASKED), LI_ASKED
        assert "Business Insights Analyst - Emiratization Graduate Programme" not in titles5  # dropped unread
        assert pages["wanted"] == 4 and pages["blocked"] == 1 and pages["read"] == len(LI_ASKED) - 1, pages
        assert pages["skipped"] == 4 - len(LI_ASKED) and pages["dropped"] == {"nationals-only": 1}, pages
        acme = titles5["Junior Data Scientist"]
        assert acme["is_new"] and "0-1 years" in acme["snippet"] and acme["min_years"] == 0, acme
        assert "Graduate Data Analyst Programme" not in titles5 and "MIS Analyst" not in titles5
        assert not titles5["Data Engineer Trainee"]["is_new"] and titles5["Junior AI Engineer"]["snippet"] == ""
        assert "jobspy:linkedin" in titles5["Junior Python Developer"]["seen_on"]
        sample5 = json.load(open(os.path.join(run.DATA, "rejected_sample.json")))
        gulf = [x for x in sample5 if x["employer"] == "Gulf Bank"][0]
        assert gulf["reason"] == "nationals-only" and "open to UAE Nationals only" in gulf["why"], gulf
        # the LinkedIn copy of Oracle's nationals-only job has no words of its own: it takes Oracle's verdict
        mis = [x for x in sample5 if x["source"] == "jobspy:linkedin" and x["title"] == "MIS Analyst"][0]
        assert mis["reason"] == "nationals-only" and mis["from"] == "oracle:ADIB", mis
        assert latest5["summary"]["verdicts_shared"] == 1
        md = open(os.path.join(run.DATA, "latest.md"), encoding="utf-8").read()
        assert "**LinkedIn pages:**" in md and "1 dropped after reading (1 nationals-only)" in md, md[:1500]
        assert "stopped at a refusal (429 /jobs/view/9006)" in md

        # a second full run the same day: pages already read come from the cache, the daily limit holds
        LI_PAGES["9006"] = (200, "/jobs/view/9006", "Entry level. 1 year of experience.")
        del LI_ASKED[:]
        search["linkedin_pages"] = 1
        run.main()
        latest6 = json.load(open(os.path.join(run.DATA, "latest.json")))
        titles6 = {j["title"]: j for j in latest6["jobs"]}
        pages = latest6["summary"]["status"]["linkedin_pages"]
        assert len(LI_ASKED) == 1 and LI_ASKED[0] in {"9006", "9007"}, LI_ASKED
        assert pages["wanted"] == 2 and pages["read"] == 1 and pages["over_limit"] == 1, pages
        assert "Graduate Data Analyst Programme" not in titles6 and "Junior Data Scientist" in titles6
        assert titles6["Junior Data Scientist"]["is_new"]  # still new today
        sample6 = json.load(open(os.path.join(run.DATA, "rejected_sample.json")))
        gulf = [x for x in sample6 if x["employer"] == "Gulf Bank"][0]  # its words come from the cache now
        assert gulf["reason"] == "nationals-only" and "open to UAE Nationals only" in gulf["why"], gulf
        print("offline end-to-end run passes")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
