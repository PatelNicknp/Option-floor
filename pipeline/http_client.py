"""Polite HTTP with retries. One client is shared for a whole run."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SEC_UA = "OptionsFloor/1.0 (educational research; admin@optionsfloor.local)"


class HttpClient:
    def __init__(self, pause: float = 0.4, retries: int = 3, timeout: float = 25.0) -> None:
        self.pause = pause
        self.retries = retries
        self.timeout = timeout
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cookies))
        self._last = 0.0
        self.crumb: str | None = None

    def _wait(self) -> None:
        if self.pause <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self.pause:
            time.sleep(self.pause - elapsed)

    def get(self, url: str, headers: dict | None = None, accept: tuple[int, ...] = (200,)) -> tuple[int, bytes]:
        merged = {"User-Agent": BROWSER_UA, "Accept": "*/*"}
        if headers:
            merged.update(headers)
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._wait()
            request = urllib.request.Request(url, headers=merged)
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    self._last = time.monotonic()
                    status = int(getattr(response, "status", 200))
                    body = response.read()
                    if status in accept:
                        return status, body
                    last_error = RuntimeError(f"HTTP {status}")
            except urllib.error.HTTPError as exc:
                self._last = time.monotonic()
                body = exc.read()
                if exc.code in accept:
                    return exc.code, body
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
            except Exception as exc:  # noqa: BLE001 - keep the run alive at the caller
                self._last = time.monotonic()
                last_error = exc
            time.sleep(min(8.0, 0.8 * (2**attempt)))
        raise RuntimeError(f"Failed {url}: {last_error}")

    def get_json(self, url: str, headers: dict | None = None) -> dict:
        _, body = self.get(url, headers=headers)
        return json.loads(body.decode("utf-8", "replace"))

    def ensure_yahoo(self) -> None:
        if self.crumb:
            return
        try:
            self.get("https://fc.yahoo.com", accept=(200, 404, 400))
        except Exception:
            pass
        _, body = self.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
        crumb = body.decode("utf-8", "replace").strip().strip('"')
        if not crumb or crumb.startswith("<") or " " in crumb or len(crumb) > 50:
            raise RuntimeError("Yahoo did not return a usable crumb")
        self.crumb = crumb

    def yahoo_json(self, url: str) -> dict:
        self.ensure_yahoo()
        full = _with_crumb(url, self.crumb or "")
        try:
            return self.get_json(full)
        except Exception:
            self.crumb = None
            self.ensure_yahoo()
            return self.get_json(_with_crumb(url, self.crumb or ""))


def _with_crumb(url: str, crumb: str) -> str:
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}crumb={urllib.parse.quote(crumb)}"


def attempt(health: list[dict], source_id: str, label: str, fn, empty):
    """Run one source. On failure, record it and keep going."""
    try:
        value = fn()
        health.append({"id": source_id, "label": label, "ok": True, "detail": _detail(value)})
        return value
    except Exception as exc:  # noqa: BLE001 - a dead wire must not stop the run
        health.append(
            {
                "id": source_id,
                "label": label,
                "ok": False,
                "detail": f"Skipped. {exc}"[:300],
            }
        )
        return empty


def _detail(value) -> str:
    if isinstance(value, dict):
        return f"{len(value)} rows"
    if isinstance(value, (list, tuple)):
        return f"{len(value)} items"
    if value is None:
        return "No data"
    return "Loaded"
