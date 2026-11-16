"""The polite client's queues, without a network. Run: python -m tests.test_http"""
import types

from engine import http as http_mod
from engine.http import Http, LeftAlone


class FakeSession:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.asked = []

    def request(self, method, url, **kw):
        self.asked.append(url)
        status = self.statuses.pop(0) if self.statuses else 200
        return types.SimpleNamespace(status_code=status, headers={}, text="")


def client(statuses):
    slept = []
    http = Http(min_interval=1.0)
    session = FakeSession(statuses)
    http._session = lambda: session
    http_mod.time.sleep = slept.append  # record the waits instead of waiting
    return http, session, slept


def main():
    real_sleep = http_mod.time.sleep
    try:
        # every Workday employer waits in one queue; other hosts keep their own
        assert Http.lane("medtronic.wd1.myworkdayjobs.com") == Http.lane("kbr.wd5.myworkdayjobs.com")
        assert Http.lane("boards-api.greenhouse.io") == "boards-api.greenhouse.io"

        # two Workday employers one after the other: the second waits about 2 seconds
        http, session, slept = client([200, 200, 200])
        http.get("https://medtronic.wd1.myworkdayjobs.com/a")
        http.get("https://kbr.wd5.myworkdayjobs.com/b")
        http.get("https://boards-api.greenhouse.io/c")  # another host: no wait
        assert len(slept) == 1 and 1.5 < slept[0] <= 2.0, slept

        # a 429 makes the whole queue wait, and the request is tried again
        http, session, slept = client([429, 200])
        assert http.get("https://medtronic.wd1.myworkdayjobs.com/a").status_code == 200
        assert len(session.asked) == 2 and any(14 < s <= 15 for s in slept), slept

        # three 429 answers in a row: the job system is left alone for the rest of the run
        http, session, slept = client([429, 429, 429, 200, 200])
        assert http.get("https://medtronic.wd1.myworkdayjobs.com/a").status_code == 429  # after two retries
        for url in ("https://kbr.wd5.myworkdayjobs.com/b", "https://gsk.wd5.myworkdayjobs.com/c"):
            try:
                http.get(url)
                raise AssertionError("asked again after three refusals")
            except LeftAlone as e:
                assert "myworkdayjobs.com answered 429 3 times in a row" in str(e), e
        assert len(session.asked) == 3, session.asked  # nothing was sent after the third refusal
        assert http.get("https://boards-api.greenhouse.io/c").status_code == 200  # other hosts go on

        # an answer in between resets the count
        http, session, slept = client([429, 200, 429, 200, 429, 200])
        for _ in range(3):
            assert http.get("https://kbr.wd5.myworkdayjobs.com/b").status_code == 200
        # a crawl-delay set for a host applies to its queue
        http, session, slept = client([200, 200])
        http.set_gap("careers.example-jibe.com", 5)
        http.get("https://careers.example-jibe.com/api/jobs?page=1")
        http.get("https://careers.example-jibe.com/api/jobs?page=2")
        assert len(slept) == 1 and 4.5 < slept[0] <= 5.0, slept
        print("all polite-client cases pass")
    finally:
        http_mod.time.sleep = real_sleep


if __name__ == "__main__":
    main()
