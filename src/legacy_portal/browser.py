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

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw
from playwright.sync_api import Error as PWError
from playwright.sync_api import Frame, Locator, Page
from playwright.sync_api import TimeoutError as PWTimeout

MAX_SNAPSHOT_CHARS = 16000  # 7000 cut off long pages (held-out C, all months expanded) -> safe but needless handoff
MARK_ROLES = ("link", "button", "textbox", "combobox", "checkbox", "tab")
CLICKABLE_CSS = "summary, [onclick], [role=tab], [tabindex]:not([tabindex='-1'])"
MAX_MARKS = 120
MAX_LOGIN_POSTS = 3  # C4 account safety: more than this and the run is stopped in code, whatever the model wants


# A nameless link or button can do anything (mail a letter, cancel an order). Acting on one without having seen it
# is a guess, and the prompt rule against guessing was not enough (D13: 3 and 6 letters mailed without vision).
# So it is enforced here: only a mark from a look, i.e. an element the model has seen, can be used.
BLIND = ("this element has no name, so its purpose is unknown; use look and address it by its mark "
         "(or hand off) instead of guessing by position or URL")


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
    login_posts: int = 0

    popups: list = field(default_factory=list)
    marks: dict[int, Locator] = field(default_factory=dict)  # set by look(); valid until the page changes

    def __post_init__(self):
        def count(req):
            if req.method == "POST" and "login" in req.url.lower():
                self.login_posts += 1
        self.page.on("request", count)
        def on_new_tab(new_page):  # links with target=_blank open new tabs (Playwright needs a real function)
            self.popups.append(new_page)
        self.page.context.on("page", on_new_tab)

    def _closed_popups(self) -> list[str]:
        """Close tabs opened by the last action and report where they went; the agent works in one tab."""
        self.page.wait_for_timeout(300)
        urls = []
        for pop in self.popups:
            urls.append(pop.url if pop.url != "about:blank" else "(a file or download)")
            pop.close()
        self.popups.clear()
        return urls

    @property
    def login_limit_hit(self) -> bool:
        return self.login_posts > MAX_LOGIN_POSTS

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

    def look(self) -> tuple[bytes, str]:
        """Vision fallback (D2): a screenshot with a numbered box on every interactive element ("set-of-marks"),
        plus a legend. The model answers with "mark": N and code clicks that exact element: no guessed pixels."""
        self.marks.clear()
        boxes, legend, seen_boxes = [], [], set()
        for label, f in self.frames():
            # Standard roles, plus clickable things with no standard role (found on held-out Portal C:
            # collapsible <summary> headers): tabs, click handlers, pointer-styled elements.
            sources = [(role, f.get_by_role(role)) for role in MARK_ROLES]
            sources.append(("clickable", f.locator(CLICKABLE_CSS)))
            for role, loc in sources:
                for i in range(loc.count()):
                    if len(self.marks) >= MAX_MARKS:
                        break
                    el = loc.nth(i)
                    try:
                        box = el.bounding_box(timeout=1000)
                        name = (el.get_attribute("aria-label", timeout=500) or el.inner_text(timeout=500) or "").strip()
                    except (PWError, PWTimeout):
                        continue
                    if not box or box["width"] < 2 or box["height"] < 2:
                        continue
                    key = (label, round(box["x"]), round(box["y"]), round(box["width"]))
                    if key in seen_boxes:  # already marked under a standard role
                        continue
                    seen_boxes.add(key)
                    n = len(self.marks) + 1
                    self.marks[n] = el
                    boxes.append((n, box))
                    legend.append(f"[{n}] {role} {name.splitlines()[0][:40] if name else ''!r} (frame {label!r})")
        # Full page, not just the visible window (a cut-off screenshot made the agent unsure the list was complete).
        # bounding_box() is relative to the viewport, so shift every box by the page's scroll offset.
        sx, sy = self.page.evaluate("[window.scrollX, window.scrollY]")
        img = Image.open(io.BytesIO(self.page.screenshot(full_page=True))).convert("RGB")
        draw = ImageDraw.Draw(img)
        for n, b in boxes:
            x, y, w, h = b["x"] + sx, b["y"] + sy, b["width"], b["height"]
            draw.rectangle([x - 1, y - 1, x + w + 1, y + h + 1], outline=(230, 0, 0), width=2)
            draw.rectangle([x - 1, y - 13, x + 7 * len(str(n)) + 3, y - 1], fill=(230, 0, 0))
            draw.text((x + 1, y - 13), str(n), fill=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        (self.out_dir / f"look-{len(list(self.out_dir.glob('look-*.png'))) + 1:02d}.png").write_bytes(buf.getvalue())
        return buf.getvalue(), "\n".join(legend)

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

    def _target(self, action: dict) -> Locator:
        mark = action.get("mark")
        if mark is not None:
            if mark not in self.marks:
                raise LookupError(f"mark {mark} is not on the last look (marks expire when the page changes; look again)")
            return self.marks[mark]
        if action.get("text") and not action.get("role"):
            return self._locate_text(action.get("frame", ""), action["text"], action.get("nth"))
        if action.get("role") in ("link", "button") and not action.get("name"):
            raise LookupError(BLIND)
        return self._locate(action.get("frame", ""), action.get("role", ""), action.get("name", ""), action.get("nth"))

    def _nameless_hrefs(self) -> set[str]:
        """Absolute URLs of links on the page that have no accessible name (icons without alt text or label)."""
        js = """() => [...document.querySelectorAll('a[href]')].filter(a => !a.innerText.trim()
            && !a.getAttribute('aria-label') && !a.getAttribute('title')
            && ![...a.querySelectorAll('img')].some(i => (i.alt || '').trim())).map(a => a.href)"""
        urls: set[str] = set()
        for f in self.page.frames:
            try:
                urls.update(f.evaluate(js))
            except PWError:
                pass
        return urls

    def _locate_text(self, frame: str, text: str, nth: int | None = None) -> Locator:
        """By visible text, for clickable things with no standard role (e.g. a collapsed section header).
        Same rule as roles: several matches without nth is an error, never a guess."""
        loc = self._frame(frame).get_by_text(text, exact=True)
        n = loc.count()
        if n == 0:
            raise LookupError(f"no element with the exact text {text!r} in frame {frame or 'top'!r}")
        if nth is not None:
            if not 0 <= nth < n:
                raise LookupError(f"nth={nth} out of range: {n} elements with text {text!r}")
            return loc.nth(nth)
        if n > 1:
            raise LookupError(f"{n} elements with the text {text!r}; add nth (0-based, in page order)")
        return loc.first

    def _fill_secrets(self, value: str) -> str:
        return re.sub(r"\{\{(\w+)\}\}", lambda m: self.secrets.get(m.group(1), m.group(0)), value)

    def run(self, action: dict) -> ActionResult:
        kind = action.get("action")
        _frame, role, name, value = (action.get(k, "") for k in ("frame", "role", "name", "value"))
        if kind in ("fill", "select") and not value:
            # never type an empty string and report success: say what was wrong (D13)
            hint = f" (you sent text={action['text']!r}; \"text\" only addresses elements)" if action.get("text") else ""
            return ActionResult(False, f"{kind} needs \"value\": the text to type or the option to choose{hint}")
        try:
            if kind == "click":
                self._target(action).click(timeout=5000)
                if action.get("text") and not role:
                    name = action["text"]
                opened = self._closed_popups()
                if opened:
                    return ActionResult(True, f"clicked {role} {name!r}: it opened a new tab at {opened[0]} (closed). "
                                              "To save a document, use the download action on that same link.")
                return ActionResult(True, f"clicked {role} {name!r}")
            if kind == "fill":
                self._target(action).fill(self._fill_secrets(value), timeout=5000)
                shown = value if "{{" in value else value[:40]
                return ActionResult(True, f"filled {role} {name!r} with {shown!r}")
            if kind == "select":
                self._target(action).select_option(label=value, timeout=5000)
                return ActionResult(True, f"selected {value!r} in {name!r}")
            if kind == "goto":
                url = urljoin(self.page.url, value)
                if urlparse(url).netloc != urlparse(self.allowed_origin).netloc:
                    return ActionResult(False, f"blocked: {url} is outside the allowed portal")
                if url in self._nameless_hrefs():
                    return ActionResult(False, f"blocked: {BLIND}")
                try:
                    self.page.goto(url)
                except PWError as e:
                    if "Download is starting" not in str(e):
                        raise
                    # The URL is a file, not a page: fetch it through the session like a link download.
                    return self._fetch_pdf(url, self._seen("top"))
                return ActionResult(True, f"opened {url}")
            if kind == "download":
                return self._download(action)
            return ActionResult(False, f"unknown action {kind!r}")
        except (LookupError, PWTimeout, PWError) as e:  # any browser error is a failed action, never a crash
            return ActionResult(False, f"failed: {str(e).splitlines()[0][:200]}")

    def _seen(self, frame: str) -> str:
        try:
            return self._frame(frame).locator("body").aria_snapshot(timeout=3000)
        except (PWError, LookupError):
            return ""

    def _download(self, action: dict) -> ActionResult:
        el = self._target(action)
        frame_url = el.evaluate("e => e.ownerDocument.location.href")
        seen = el.evaluate("e => e.ownerDocument.body ? e.ownerDocument.body.innerText : ''")
        try:  # prefer the accessibility snapshot of the element's frame when we know it by label
            if action.get("mark") is None:
                seen = self._seen(action.get("frame", ""))
        except LookupError:
            pass
        href = el.get_attribute("href")
        if not href or href == "#":
            return ActionResult(False, "that element has no download link (open the document details first?)")
        return self._fetch_pdf(urljoin(frame_url, href), seen)

    def _fetch_pdf(self, url: str, seen: str) -> ActionResult:
        if urlparse(url).netloc != urlparse(self.allowed_origin).netloc:
            return ActionResult(False, f"blocked: {url} is outside the allowed portal")
        resp = self.page.context.request.get(url)  # same cookies as the logged-in page
        if "application/pdf" not in resp.headers.get("content-type", ""):
            landed = urlparse(resp.url).path
            if "login" in resp.url.lower() or 'type="password"' in resp.text().lower():
                return ActionResult(False, f"session expired: the portal sent its login page ({landed}) instead of the "
                                           f"PDF. Log in again (goto {landed}) and continue; downloads so far are kept.")
            return ActionResult(False, f"not a PDF (HTTP {resp.status}, landed on {landed})")
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
