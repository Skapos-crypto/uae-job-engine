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


class Http:
    def __init__(self, min_interval=1.0, timeout=40):
        self.min_interval = min_interval
        self.timeout = timeout
        self._locks = {}
        self._last = {}
        self._gaps = {}
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

    def _host_lock(self, host):
        with self._guard:
            if host not in self._locks:
                self._locks[host] = threading.Lock()
            return self._locks[host]

    def set_gap(self, host, seconds):
        """Wait longer than min_interval between requests to one host (its robots.txt crawl-delay)."""
        self._gaps[host] = max(seconds, self.min_interval)

    def request(self, method, url, retries=2, **kw):
        host = urlparse(url).netloc
        kw.setdefault("timeout", self.timeout)
        lock = self._host_lock(host)
        need = self._gaps.get(host, self.min_interval)
        attempt = 0
        while True:
            with lock:
                gap = time.time() - self._last.get(host, 0)
                if gap < need:
                    time.sleep(need - gap)
                try:
                    resp = self._session().request(method, url, **kw)
                finally:
                    self._last[host] = time.time()
                    self.calls += 1
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                attempt += 1
                wait = resp.headers.get("Retry-After")
                time.sleep(min(int(wait), 30) if wait and wait.isdigit() else 4 * attempt)
                continue
            return resp

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
