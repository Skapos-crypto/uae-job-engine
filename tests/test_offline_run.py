"""End-to-end run against canned API responses (no network). Run: python -m tests.test_offline_run"""
import json
import logging
import os
import random
import shutil
import sys
import tempfile
import types

import run
from engine import http as http_mod

FAILING = set()  # board tokens that answer 404, to exercise carry-over
SCRAPES = {"linkedin": 0, "bayt": 0}  # JobSpy calls per site, to check that a blocked site is left alone


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
        logging.getLogger("jobspy.linkedin").error("response status code 429 (blocked: use a proxy)")
        return FakeFrame([])
    assert kw.get("location") == "UAE", kw  # Bayt must be asked for the UAE, not every country
    return FakeFrame([{"job_url": "https://www.bayt.com/en/uae/jobs/data-analyst-1/", "company": "Acme",
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
             "description": "<p>2 years of experience</p>"}]})
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
                         "site": "CorporateCareers"}],
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
        http_mod.Http.request = fake_request
        sys.modules["jobspy"] = types.ModuleType("jobspy")
        sys.modules["jobspy"].scrape_jobs = fake_scrape_jobs
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
                       "Junior Python Engineer"}
        assert set(titles) == expect_kept, set(titles) ^ expect_kept
        # Avature: the job page gave the location; the candidate whose page says United Kingdom is out
        assert titles["Graduate Data Analyst"]["location"] == "United Arab Emirates"
        assert titles["Graduate Data Analyst"]["posted"] == "2026-10-09"
        assert latest["summary"]["rejected"].get("not-uae") == 1
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
        assert health["_details"]["fetched"] == 10, health["_details"]  # every candidate with a detail page

        # midday run: JobSpy is skipped and one board fails; their jobs are carried and stay new today
        FAILING.add("careem")
        os.environ["FULL_RUN"] = "0"
        run.main()
        latest3 = json.load(open(os.path.join(run.DATA, "latest.json")))
        titles3 = {j["title"]: j for j in latest3["jobs"]}
        assert set(titles3) == expect_kept, set(titles3) ^ expect_kept
        assert latest3["summary"]["carried_over"] == 2
        assert titles3["Junior Data Analyst"]["is_new"] and titles3["Data Scientist"]["is_new"]
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
        print("offline end-to-end run passes")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
