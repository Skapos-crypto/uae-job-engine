"""End-to-end run against canned API responses (no network). Run: python -m tests.test_offline_run"""
import json
import os
import shutil
import tempfile

import run
from engine import http as http_mod


class FakeResp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = {}

    def json(self):
        return self._payload


def fake_request(self, method, url, retries=2, **kw):
    self.calls += 1
    if "recruitingCESites" in url:
        return FakeResp({"items": [{"SiteNumber": "CX_1"}, {"SiteNumber": "INTERNAL"}]})
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
        return FakeResp({"total": 2, "jobPostings": [
            {"title": "Associate Analyst, Data & Services", "externalPath": "/job/Dubai/Associate-Analyst_R-1",
             "locationsText": "Dubai, United Arab Emirates", "postedOn": "Posted 2 Days Ago"},
            {"title": "Director, Product", "externalPath": "/job/Dubai/Director_R-2",
             "locationsText": "Dubai, United Arab Emirates", "postedOn": "Posted Today"}]})
    if "/wday/cxs/" in url:
        return FakeResp({"jobPostingInfo": {"jobDescription": "<p>1+ years of experience with SQL</p>"}})
    if "boards-api" in url:
        if "/boards/careem/" not in url:
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
            "oracle": [{"name": "ADIB", "sector": "banking", "host": "x.oraclecloud.com", "sites": []}],
            "workday": [{"name": "Mastercard", "sector": "payments", "tenant": "mastercard", "wd": "wd1",
                         "site": "CorporateCareers"}],
            "boards": [{"ats": "greenhouse", "token": "careem", "name": "Careem"},
                       {"ats": "lever", "token": "aldar", "name": "Aldar"},
                       {"ats": "ashby", "token": "ziina", "name": "Ziina"},
                       {"ats": "workable", "token": "bayutdubizzle"}],
            "amazon": True,
            "probe": ["nosuchco"],
        }
        run.load_yaml = lambda name: cfg if name == "employers.yaml" else {"jobspy": {}}
        http_mod.Http.request = fake_request
        os.environ["FULL_RUN"] = "1"  # exercises the probe; jobspy list is empty
        run.main()

        latest = json.load(open(os.path.join(run.DATA, "latest.json")))
        titles = {j["title"]: j for j in latest["jobs"]}
        print("\nkept:", sorted(titles))
        print("rejected:", latest["summary"]["rejected"])
        expect_kept = {"HR Data Analyst", "Associate Analyst, Data & Services", "Data Scientist",
                       "Graduate Programme - Data & Technology", "Junior Python Developer", "Data Analyst",
                       "Business Intelligence Engineer"}
        assert set(titles) == expect_kept, set(titles) ^ expect_kept
        assert "stretch_3y" in titles["Business Intelligence Engineer"]["flags"]
        assert "own_visa_preferred" in titles["Junior Python Developer"]["flags"]
        assert titles["HR Data Analyst"]["url"].endswith("/sites/CX_1/job/101")
        assert latest["summary"]["rejected"].get("nationals-only") == 1
        assert latest["summary"]["rejected"].get("4+ years") == 1
        assert os.path.exists(os.path.join(run.DATA, "latest.md"))
        cache = json.load(open(os.path.join(run.DATA, "detail_cache.json")))
        assert len(cache) >= 4

        # second run the same day: details come from the cache; first_seen is kept
        run.main()
        latest2 = json.load(open(os.path.join(run.DATA, "latest.json")))
        assert {j["title"] for j in latest2["jobs"]} == expect_kept
        assert all(j["first_seen"] == latest["jobs"][0]["first_seen"] for j in latest2["jobs"])
        health = json.load(open(os.path.join(run.DATA, "health.json")))["sources"]
        assert health["_details"]["fetched"] == 0, health["_details"]
        print("offline end-to-end run passes")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
