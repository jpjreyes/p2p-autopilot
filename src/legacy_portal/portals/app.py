"""Three mock supplier portals with no API, each "legacy" in its own way.

  /a  Acme SupplierNet       frameset layout, paginated table, US dates, PDF per row
  /b  Valvex B2B Portal       cookie wall, search form required, details in a modal, European dates and amounts
  /c  SafeGuard Vendor Center (HELD OUT: never used while tuning the agent) tabs, month accordions, "show older"

Run:  uv run uvicorn legacy_portal.portals.app:app --port 8061
Dev credentials are in CREDENTIALS below (test environment only).
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from legacy_portal.data.generate import generate
from legacy_portal.portals import chaos
from legacy_portal.portals.pdf import fmt_date, fmt_money, render

CREDENTIALS = {
    "a": ("acme_ap", "acme-pass-2026"),
    "b": ("ap@northline-distribution.example", "valvex-pass-2026"),
    "c": ("northline", "sg-pass-2026"),
}
SESSION_TTL_S = int(os.environ.get("PORTAL_SESSION_TTL_S", "900"))
ADMIN_TOKEN = os.environ.get("PORTAL_ADMIN_TOKEN", "dev-admin-token")
PAGE_SIZE = {"a": 8, "b": 10}

DATA = generate()
SUPPLIERS = {s["portal"]: s for s in DATA["suppliers"]}
DOCS: dict[str, list[dict]] = {p: sorted((d for d in DATA["documents"] if d["portal"] == p),
                                         key=lambda d: d["issue_date"], reverse=True) for p in "abc"}

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals.update(fmt_date=fmt_date, fmt_money=fmt_money, quote=quote)

app = FastAPI(title="Mock supplier portals", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("PORTAL_SESSION_SECRET", "dev-only-secret"),
                   session_cookie="portal_session", max_age=None)


# --------------------------------------------------------------------------------------------- shared helpers

class NeedsLogin(Exception):
    def __init__(self, portal: str, reason: str = ""):
        self.portal, self.reason = portal, reason


@app.exception_handler(NeedsLogin)
async def _to_login(request: Request, exc: NeedsLogin):
    url = f"/{exc.portal}/login" + (f"?reason={exc.reason}" if exc.reason else "")
    # Inside portal A's frameset, the login page must replace the whole window, like the real thing.
    return RedirectResponse(url, status_code=303)


def session_guard(portal: str):
    async def guard(request: Request):
        if chaos.active(portal, "slow"):
            await asyncio.sleep(random.uniform(2, 4))
        s = request.session.get(portal)
        if not s:
            raise NeedsLogin(portal)
        if s.get("expired") or time.time() - s["t"] > SESSION_TTL_S:
            request.session.pop(portal, None)
            raise NeedsLogin(portal, "expired")
        return s
    return guard


GUARD = {p: Depends(session_guard(p)) for p in "abc"}


async def maybe_slow(portal: str):
    if chaos.active(portal, "slow"):
        await asyncio.sleep(random.uniform(2, 4))


def ctx(request: Request, portal: str, **kw) -> dict:
    return {"request": request, "supplier": SUPPLIERS[portal],
            "variant": chaos.active(portal, "layout_variant"), "renamed": chaos.active(portal, "renamed_fields"), **kw}


def find_doc(portal: str, number: str) -> dict:
    for d in DOCS[portal]:
        if d["number"] == number:
            return d
    raise HTTPException(404, "Document not found")


def pdf_response(request: Request, portal: str, number: str) -> Response:
    doc = find_doc(portal, number)
    if chaos.fire_once(portal, "session_expiry"):
        # Reassign the top-level key: Starlette only saves the session when a top-level key changes.
        request.session[portal] = {**request.session[portal], "expired": True}  # NEXT request bounces to login
    fname = number.replace("/", "-") + ".pdf"
    return Response(render(doc, SUPPLIERS[portal]), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


async def do_login(request: Request, portal: str, user: str, password: str, captcha: str | None):
    await maybe_slow(portal)
    if chaos.active(portal, "captcha"):
        return templates.TemplateResponse(request, f"{portal}/login.html",
                                          ctx(request, portal, error="Verification failed. Please try again.",
                                              captcha=True), status_code=401)
    if (user, password) != CREDENTIALS[portal]:
        return templates.TemplateResponse(request, f"{portal}/login.html",
                                          ctx(request, portal, error="Invalid username or password.",
                                              captcha=False), status_code=401)
    request.session[portal] = {"user": user, "t": time.time()}
    return RedirectResponse({"a": "/a/", "b": "/b/documents", "c": "/c/home"}[portal], status_code=303)


async def login_page(request: Request, portal: str, reason: str = ""):
    await maybe_slow(portal)
    msg = "Your session has expired. Please sign in again." if reason == "expired" else ""
    return templates.TemplateResponse(request, f"{portal}/login.html",
                                      ctx(request, portal, notice=msg, captcha=chaos.active(portal, "captcha")))


def logout(request: Request, portal: str):
    request.session.pop(portal, None)
    return RedirectResponse(f"/{portal}/login", status_code=303)


# --------------------------------------------------------------------------------------------- portal A

a = APIRouter(prefix="/a")


@a.get("/login", response_class=HTMLResponse)
async def a_login_page(request: Request, reason: str = ""):
    return await login_page(request, "a", reason)


@a.post("/login")
async def a_login(request: Request, username: str = Form(""), password: str = Form(""), captcha: str = Form(None)):
    return await do_login(request, "a", username, password, captcha)


@a.get("/logout")
async def a_logout(request: Request):
    return logout(request, "a")


@a.get("/", response_class=HTMLResponse)
async def a_frameset(request: Request, s=GUARD["a"]):
    return templates.TemplateResponse(request, "a/frameset.html", ctx(request, "a"))


@a.get("/nav", response_class=HTMLResponse)
async def a_nav(request: Request, s=GUARD["a"]):
    return templates.TemplateResponse(request, "a/nav.html", ctx(request, "a", user=s["user"]))


@a.get("/welcome", response_class=HTMLResponse)
async def a_welcome(request: Request, s=GUARD["a"]):
    n_open = sum(d["status"] == "open" for d in DOCS["a"])
    return templates.TemplateResponse(request, "a/welcome.html", ctx(request, "a", n_open=n_open))


@a.get("/invoices", response_class=HTMLResponse)
async def a_invoices(request: Request, page: int = 1, s=GUARD["a"]):
    docs = DOCS["a"]
    pages = max(1, -(-len(docs) // PAGE_SIZE["a"]))
    page = min(max(page, 1), pages)
    rows = docs[(page - 1) * PAGE_SIZE["a"]: page * PAGE_SIZE["a"]]
    return templates.TemplateResponse(request, "a/invoices.html",
                                      ctx(request, "a", rows=rows, page=page, pages=pages, total=len(docs)))


@a.get("/doc")
async def a_doc(request: Request, no: str, s=GUARD["a"]):
    return pdf_response(request, "a", no)


# --------------------------------------------------------------------------------------------- portal B

b = APIRouter(prefix="/b")


@b.get("/login", response_class=HTMLResponse)
async def b_login_page(request: Request, reason: str = ""):
    return await login_page(request, "b", reason)


@b.post("/login")
async def b_login(request: Request, email: str = Form(""), password: str = Form(""), captcha: str = Form(None)):
    return await do_login(request, "b", email, password, captcha)


@b.get("/logout")
async def b_logout(request: Request):
    return logout(request, "b")


def _parse_de(value: str) -> date | None:
    return datetime.strptime(value.strip(), "%d.%m.%Y").date() if value.strip() else None


@b.get("/documents", response_class=HTMLResponse)
async def b_documents(request: Request, date_from: str = "", date_to: str = "", status: str = "all",
                      page: int = 1, searched: int = 0, s=GUARD["b"]):
    error, rows, pages = "", None, 1
    if searched:
        try:
            lo, hi = _parse_de(date_from), _parse_de(date_to)
        except ValueError:
            error = "Please enter dates as DD.MM.YYYY (TT.MM.JJJJ)."
        else:
            hits = [d for d in DOCS["b"]
                    if (status == "all" or d["status"] == status)
                    and (lo is None or date.fromisoformat(d["issue_date"]) >= lo)
                    and (hi is None or date.fromisoformat(d["issue_date"]) <= hi)]
            pages = max(1, -(-len(hits) // PAGE_SIZE["b"]))
            page = min(max(page, 1), pages)
            rows = hits[(page - 1) * PAGE_SIZE["b"]: page * PAGE_SIZE["b"]]
    return templates.TemplateResponse(request, "b/documents.html",
                                      ctx(request, "b", rows=rows, error=error, page=page, pages=pages,
                                          q={"date_from": date_from, "date_to": date_to, "status": status}))


@b.get("/download")
async def b_download(request: Request, doc: str, s=GUARD["b"]):
    return pdf_response(request, "b", doc)


# --------------------------------------------------------------------------------------------- portal C (held out)

c = APIRouter(prefix="/c")


@c.get("/login", response_class=HTMLResponse)
async def c_login_page(request: Request, reason: str = ""):
    return await login_page(request, "c", reason)


@c.post("/login")
async def c_login(request: Request, username: str = Form(""), password: str = Form(""), captcha: str = Form(None)):
    return await do_login(request, "c", username, password, captcha)


@c.get("/logout")
async def c_logout(request: Request):
    return logout(request, "c")


@c.get("/home", response_class=HTMLResponse)
async def c_home(request: Request, s=GUARD["c"]):
    return templates.TemplateResponse(request, "c/home.html", ctx(request, "c", tab="dashboard"))


@c.get("/billing", response_class=HTMLResponse)
async def c_billing(request: Request, older: int = 0, s=GUARD["c"]):
    months: dict[str, list[dict]] = {}
    for d in DOCS["c"]:
        months.setdefault(d["issue_date"][:7], []).append(d)
    keys = sorted(months, reverse=True)
    shown = keys if older else keys[:2]
    return templates.TemplateResponse(request, "c/billing.html",
                                      ctx(request, "c", tab="billing", months=[(k, months[k]) for k in shown],
                                          has_older=len(keys) > len(shown)))


@c.get("/billing/{number}/pdf")
async def c_pdf(request: Request, number: str, s=GUARD["c"]):
    return pdf_response(request, "c", number)


# --------------------------------------------------------------------------------------------- admin + index

class ChaosRequest(BaseModel):
    portal: str
    modes: list[str]


@app.post("/admin/chaos")
def set_chaos(body: ChaosRequest, x_admin_token: str = Header("")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "bad admin token")
    try:
        chaos.set_modes(body.portal, body.modes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return chaos.snapshot()


@app.get("/admin/chaos")
def get_chaos():
    return chaos.snapshot()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    items = "".join(f'<li><a href="/{p}/login">{SUPPLIERS[p]["name"]}</a>'
                    f'{" (held out)" if SUPPLIERS[p]["held_out"] else ""}</li>' for p in "abc")
    return f"<h1>Mock supplier portals (test environment)</h1><ul>{items}</ul>"


app.include_router(a)
app.include_router(b)
app.include_router(c)
