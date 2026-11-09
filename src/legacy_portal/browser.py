"""Browser tools for the agent (decision D2: accessibility tree first).

The agent never sees CSS selectors or raw HTML. It sees each frame's accessibility tree (roles + accessible names)
and addresses elements the same way: {"frame": "main", "role": "link", "name": "View PDF"}.

Guardrails that live here, in code:
  - credentials are placeholders ({{username}}, {{password}}): the model never sees the real secrets
  - navigation is restricted to the allowed origin (no wandering off to other sites)
  - downloads go through the logged-in browser session and must be real PDFs
  - every step gets a screenshot for the audit log
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import Frame, Page
from playwright.sync_api import TimeoutError as PWTimeout

MAX_SNAPSHOT_CHARS = 7000


@dataclass
class ActionResult:
    ok: bool
    message: str
    downloaded: str | None = None  # file path when a PDF was saved


@dataclass
class BrowserTools:
    page: Page
    allowed_origin: str
    secrets: dict[str, str]
    out_dir: Path
    downloads: list[str] = field(default_factory=list)
    contexts: dict[str, str] = field(default_factory=dict)  # pdf path -> what the page showed at download time

    # ------------------------------------------------------------------ observe
    def frames(self) -> list[tuple[str, Frame]]:
        named = []
        for i, f in enumerate(self.page.frames):
            label = "top" if f == self.page.main_frame else (f.name or f"frame{i}")
            named.append((label, f))
        return named

    def observe(self) -> str:
        self.page.wait_for_load_state("domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except PWTimeout:
            pass
        parts = [f"URL: {self.page.url}", f"Title: {self.page.title()}"]
        for label, f in self.frames():
            try:
                snap = f.locator("body").aria_snapshot(timeout=3000)
            except PWError:  # frameset documents have no body; the child frames carry the content
                snap = None
            if snap is None:
                continue
            if len(snap) > MAX_SNAPSHOT_CHARS:
                snap = snap[:MAX_SNAPSHOT_CHARS] + "\n... (truncated)"
            parts.append(f"--- frame '{label}' ({f.url}) ---\n{snap}")
        return "\n".join(parts)

    def screenshot(self, name: str) -> str:
        path = self.out_dir / f"{name}.png"
        self.page.screenshot(path=str(path))
        return str(path)

    # ------------------------------------------------------------------ act
    def _frame(self, label: str) -> Frame:
        for name, f in self.frames():
            if name == (label or "top"):
                return f
        raise LookupError(f"no frame named {label!r}; frames: {[n for n, _ in self.frames()]}")

    def _locate(self, frame: str, role: str, name: str, nth: int | None = None):
        """Role + name -> one element. Ambiguity is an error, never a silent guess (old portals often have
        several unlabeled textboxes; picking the first one typed the password into the username box)."""
        f = self._frame(frame)
        loc = f.get_by_role(role, name=name, exact=True)
        if loc.count() == 0 and name:
            loc = f.get_by_role(role, name=name)
        n = loc.count()
        if n == 0:
            raise LookupError(f"no {role} named {name!r} in frame {frame or 'top'!r}")
        if nth is not None:
            if not 0 <= nth < n:
                raise LookupError(f"nth={nth} out of range: {n} {role}(s) named {name!r}")
            return loc.nth(nth)
        if n > 1:
            raise LookupError(f"{n} {role}s named {name!r} in frame {frame or 'top'!r}; add nth (0-based, in page "
                              f"order) to pick one")
        return loc.first

    def _fill_secrets(self, value: str) -> str:
        return re.sub(r"\{\{(\w+)\}\}", lambda m: self.secrets.get(m.group(1), m.group(0)), value)

    def run(self, action: dict) -> ActionResult:
        kind = action.get("action")
        frame, role, name, value = (action.get(k, "") for k in ("frame", "role", "name", "value"))
        nth = action.get("nth")
        try:
            if kind == "click":
                self._locate(frame, role, name, nth).click(timeout=5000)
                return ActionResult(True, f"clicked {role} {name!r}")
            if kind == "fill":
                self._locate(frame, role, name, nth).fill(self._fill_secrets(value), timeout=5000)
                shown = value if "{{" in value else value[:40]
                return ActionResult(True, f"filled {role} {name!r} with {shown!r}")
            if kind == "select":
                self._locate(frame, role, name, nth).select_option(label=value, timeout=5000)
                return ActionResult(True, f"selected {value!r} in {name!r}")
            if kind == "goto":
                url = urljoin(self.page.url, value)
                if urlparse(url).netloc != urlparse(self.allowed_origin).netloc:
                    return ActionResult(False, f"blocked: {url} is outside the allowed portal")
                self.page.goto(url)
                return ActionResult(True, f"opened {url}")
            if kind == "download":
                return self._download(frame, role, name, nth)
            return ActionResult(False, f"unknown action {kind!r}")
        except (LookupError, PWTimeout) as e:
            return ActionResult(False, f"failed: {str(e).splitlines()[0][:200]}")

    def _download(self, frame: str, role: str, name: str, nth: int | None = None) -> ActionResult:
        el = self._locate(frame, role, name, nth)
        try:
            seen = self._frame(frame).locator("body").aria_snapshot(timeout=3000)
        except PWError:
            seen = ""
        href = el.get_attribute("href")
        if not href or href == "#":
            return ActionResult(False, "that element has no download link (open the document details first?)")
        url = urljoin(self._frame(frame).url, href)
        if urlparse(url).netloc != urlparse(self.allowed_origin).netloc:
            return ActionResult(False, f"blocked: {url} is outside the allowed portal")
        resp = self.page.context.request.get(url)  # same cookies as the logged-in page
        if "application/pdf" not in resp.headers.get("content-type", ""):
            return ActionResult(False, f"not a PDF (HTTP {resp.status}); the session may have expired")
        disp = resp.headers.get("content-disposition", "")
        m = re.search(r'filename="([^"]+)"', disp)
        fname = m.group(1) if m else f"doc{len(self.downloads) + 1}.pdf"
        path = self.out_dir / "pdfs" / fname
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.body())
        if str(path) not in self.downloads:
            self.downloads.append(str(path))
        self.contexts[str(path)] = seen  # the listing row / details pop-up: the second source for extraction
        return ActionResult(True, f"downloaded {fname}", downloaded=str(path))
