"""Polite HTTP client: one request at a time per host, a minimum gap between requests,
an identifying User-Agent, and a couple of retries on throttling or server errors."""
import threading
import time
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "uae-job-engine/1.0 (personal job search; low volume; "
    "+https://github.com/Skapos-crypto/uae-job-engine)"
)

# Job systems that serve many employers from one infrastructure. All their hostnames share one
# queue, so that 23 Workday employers are asked one after another and not all in the same second
# (Workday answered "429 Too Many Requests" to 19 of them on 2026-11-16). Suffix -> seconds
# between two requests.
SHARED_LANES = {".myworkdayjobs.com": 2.0}
REFUSALS_BEFORE_LEAVING = 3  # 429 answers in a row before a host is left alone for the rest of the run


class LeftAlone(Exception):
    """A host kept answering 429: it is not asked again in this run."""


class Http:
    def __init__(self, min_interval=1.0, timeout=40):
        self.min_interval = min_interval
        self.timeout = timeout
        self._locks = {}
        self._last = {}
        self._gaps = {}
        self._wait_until = {}
        self._refusals = {}
        self._guard = threading.Lock()
        self._local = threading.local()
        self.calls = 0

    def _session(self):
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"})
            self._local.session = s
        return s

    @staticmethod
    def lane(host):
        """The queue a hostname waits in: its own, or the shared one of its job system."""
        for suffix in SHARED_LANES:
            if host.endswith(suffix):
                return suffix
        return host

    def _host_lock(self, lane):
        with self._guard:
            if lane not in self._locks:
                self._locks[lane] = threading.Lock()
            return self._locks[lane]

    def set_gap(self, host, seconds):
        """Wait longer than min_interval between requests to one host (its robots.txt crawl-delay)."""
        self._gaps[self.lane(host)] = max(seconds, self.min_interval)

    def request(self, method, url, retries=2, **kw):
        lane = self.lane(urlparse(url).netloc)
        kw.setdefault("timeout", self.timeout)
        lock = self._host_lock(lane)
        need = self._gaps.get(lane, SHARED_LANES.get(lane, self.min_interval))
        attempt = 0
        while True:
            with lock:
                if self._refusals.get(lane, 0) >= REFUSALS_BEFORE_LEAVING:
                    raise LeftAlone("%s answered 429 %d times in a row: left alone for the rest of this run"
                                    % (lane.lstrip("."), REFUSALS_BEFORE_LEAVING))
                now = time.time()
                wait = max(need - (now - self._last.get(lane, 0)), self._wait_until.get(lane, 0) - now)
                if wait > 0:
                    time.sleep(wait)
                try:
                    resp = self._session().request(method, url, **kw)
                finally:
                    self._last[lane] = time.time()
                    self.calls += 1
                if resp.status_code == 429:
                    # everyone in this queue waits, not only this request
                    asked = resp.headers.get("Retry-After")
                    pause = min(int(asked), 60) if asked and asked.isdigit() else 15 * (attempt + 1)
                    self._wait_until[lane] = time.time() + pause
                    self._refusals[lane] = self._refusals.get(lane, 0) + 1
                else:
                    self._refusals[lane] = 0
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                attempt += 1
                if resp.status_code != 429:
                    time.sleep(4 * attempt)
                continue
            return resp

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
