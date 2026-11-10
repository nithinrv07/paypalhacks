"""EventRain Cover API.

Run:  uvicorn app.main:app --reload --port 8000   (from the backend folder)
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field, model_validator

from . import config, db, pricing, trigger
from .paypal import paypal


async def _loop():
    while True:
        try:
            await asyncio.to_thread(trigger.tick)
        except Exception as e:  # never let the scheduler die
            print("scheduler error:", e)
        await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    task = asyncio.create_task(_loop())
    yield
    task.cancel()


app = FastAPI(title="EventRain Cover", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PAYOUTS = [10_000, 20_000, 30_000, 50_000, 75_000, 100_000]
THRESHOLDS = [5.0, 10.0, 20.0]


# ------------------------------------------------------------------ models
class QuoteIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    start: datetime
    end: datetime
    threshold_mm: float
    payout_inr: float
    demo: bool = False
    demo_scenario: Literal["rain", "dry", "live"] = "rain"

    @model_validator(mode="after")
    def rules(self):
        if self.threshold_mm not in THRESHOLDS:
            raise ValueError(f"threshold_mm must be one of {THRESHOLDS}")
        if self.payout_inr not in PAYOUTS:
            raise ValueError(f"payout_inr must be one of {PAYOUTS}")
        hours = (self.end - self.start).total_seconds() / 3600
        if not 1 <= hours <= 12:
            raise ValueError("Event must last between 1 and 12 hours")
        if self.start.minute or self.end.minute:
            raise ValueError("Start and end must be on the hour")
        if not self.demo and self.start < datetime.now() + timedelta(hours=config.CUTOFF_HOURS):
            raise ValueError(f"Cover must be bought at least {config.CUTOFF_HOURS:g} hours before the event")
        return self


class PolicyIn(QuoteIn):
    venue: str = Field(min_length=2, max_length=120)
    event_name: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    paypal_email: EmailStr


class CaptureIn(BaseModel):
    order_id: str


class ResolveIn(BaseModel):
    decision: str  # "pay" | "reject"


# ------------------------------------------------------------------ public
@app.get("/api/config")
def get_config():
    return {"paypal_client_id": config.PAYPAL_CLIENT_ID or None, "mock_paypal": paypal.mock,
            "inr_per_usd": config.INR_PER_USD, "cutoff_hours": config.CUTOFF_HOURS,
            "payouts": PAYOUTS, "thresholds": THRESHOLDS, "margin": config.MARGIN,
            "platform_fee_inr": config.PLATFORM_FEE_INR, "demo_replay_date": config.DEMO_REPLAY_DATE, "demo_dry_date": config.DEMO_DRY_DATE,
            "demo_replay_seconds": config.DEMO_REPLAY_SECONDS}


@app.post("/api/quote")
def quote(q: QuoteIn):
    try:
        return pricing.quote(q.lat, q.lon, q.start, q.end, q.threshold_mm, q.payout_inr)
    except Exception as e:
        raise HTTPException(502, f"Could not price this event: {e}")


@app.post("/api/policies")
def create_policy(p: PolicyIn):
    # Limit total cover per area per day, so one storm can't wipe out the pool
    exposure = db.one("""SELECT COALESCE(SUM(p.payout_amount), 0) AS s FROM policies p JOIN events e ON e.id = p.event_id
                         WHERE p.status IN ('ACTIVE','TRIGGERED','FLAGGED') AND p.demo = 0
                         AND ABS(e.lat - ?) < 0.05 AND ABS(e.lon - ?) < 0.05 AND substr(e.start_time,1,10) = ?""",
                      p.lat, p.lon, p.start.date().isoformat())["s"]
    if not p.demo and exposure + p.payout_inr > config.AREA_DAY_LIMIT_INR:
        raise HTTPException(409, "Cover for this area and date is sold out. Try a smaller amount.")

    # Demo events today or tomorrow always use the live weather for their real hours
    scenario = "live" if p.demo and 0 <= (p.start.date() - datetime.now().date()).days <= 1 else p.demo_scenario
    q = pricing.quote(p.lat, p.lon, p.start, p.end, p.threshold_mm, p.payout_inr)  # price on the server, never trust client
    uid = db.run("INSERT INTO users (name, email, paypal_email) VALUES (?,?,?)", p.name, p.email, p.paypal_email)
    eid = db.run("INSERT INTO events (user_id, name, venue, lat, lon, start_time, end_time) VALUES (?,?,?,?,?,?,?)",
                 uid, p.event_name, p.venue, p.lat, p.lon, p.start.isoformat(), p.end.isoformat())
    pid = db.run("""INSERT INTO policies (event_id, threshold_mm, payout_amount, premium, probability, status,
                    quote_json, demo, demo_scenario, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 eid, p.threshold_mm, p.payout_inr, q["premium_inr"], q["probability"], "QUOTED",
                 json.dumps(q), int(p.demo), scenario, db.now(), db.now())
    return {"id": pid}


def _policy_or_404(pid: int) -> dict:
    p = trigger.load(pid)
    if not p:
        raise HTTPException(404, "Policy not found")
    return p


@app.get("/api/policies/{pid}")
def get_policy(pid: int):
    p = _policy_or_404(pid)
    out = {k: v for k, v in p.items() if k not in ("quote_json", "decision_json")}
    out["quote"] = json.loads(p["quote_json"])
    out["decision"] = json.loads(p["decision_json"]) if p["decision_json"] else None
    out["payments"] = db.all_("SELECT type, paypal_id, amount, currency, status, created_at FROM payments "
                              "WHERE policy_id = ? ORDER BY id", pid)
    out["premium_usd"] = round(p["premium"] / config.INR_PER_USD, 2)
    out["payout_usd"] = round(p["payout_amount"] / config.INR_PER_USD, 2)
    out["live"] = trigger.live(p) if p["status"] != "QUOTED" else None
    return out


@app.post("/api/policies/{pid}/order")
def create_order(pid: int):
    p = _policy_or_404(pid)
    if p["status"] != "QUOTED":
        raise HTTPException(409, "Policy is already paid")
    usd = round(p["premium"] / config.INR_PER_USD, 2)
    try:
        order = paypal.create_order(usd, pid, f"EventRain Cover - {p['event_name']} ({p['threshold_mm']:g} mm)")
    except Exception as e:
        raise HTTPException(502, f"PayPal order failed: {e}")
    return {"id": order["id"]}


def _activate(pid: int, order_id: str, capture_id: str, status: str, raw: dict):
    p = trigger.load(pid)
    if db.one("SELECT id FROM payments WHERE policy_id = ? AND type = 'PREMIUM'", pid):
        return
    db.run("INSERT INTO payments (policy_id, type, paypal_id, amount, currency, status, raw, created_at) "
           "VALUES (?,?,?,?,?,?,?,?)", pid, "PREMIUM", capture_id, round(p["premium"] / config.INR_PER_USD, 2),
           "USD", status, json.dumps({"order_id": order_id, **raw}), db.now())
    if status == "COMPLETED" and p["status"] == "QUOTED":
        db.set_status(pid, "ACTIVE")


@app.post("/api/policies/{pid}/capture")
def capture(pid: int, body: CaptureIn):
    _policy_or_404(pid)
    try:
        res = paypal.capture_order(body.order_id)
    except Exception as e:
        raise HTTPException(502, f"PayPal capture failed: {e}")
    _activate(pid, body.order_id, res["capture_id"], res["status"], {})
    return get_policy(pid)


@app.post("/api/policies/{pid}/demo/start")
def demo_start(pid: int):
    p = _policy_or_404(pid)
    if not p["demo"] or p["status"] != "ACTIVE":
        raise HTTPException(409, "Only active demo policies can be replayed")
    trigger.start_replay(pid)
    return get_policy(pid)


@app.post("/api/policies/{pid}/check")
def check_now(pid: int):
    _policy_or_404(pid)
    return trigger.check(pid)


@app.get("/api/policies/{pid}/certificate", response_class=HTMLResponse)
def certificate(pid: int):
    p = _policy_or_404(pid)
    if p["status"] == "QUOTED":
        raise HTTPException(409, "Certificate is issued after payment")
    start, end = datetime.fromisoformat(p["start_time"]), datetime.fromisoformat(p["end_time"])
    prem = db.one("SELECT paypal_id FROM payments WHERE policy_id = ? AND type = 'PREMIUM'", pid)
    e = lambda s: escape(str(s))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>EventRain Certificate #{pid}</title>
<style>body{{font-family:Georgia,serif;max-width:720px;margin:40px auto;padding:40px;border:6px double #0e4f6e;color:#10212b}}
h1{{color:#0e4f6e;margin:0}}table{{width:100%;border-collapse:collapse;margin:24px 0}}td{{padding:8px;border-bottom:1px solid #d6e2e8}}
td:first-child{{color:#5a6b75;width:40%}}.rule{{background:#eef6f9;padding:16px;border-left:4px solid #0e4f6e}}
@media print{{button{{display:none}}}}</style></head><body>
<h1>EventRain Cover</h1><p>Certificate of parametric rain cover &middot; Policy #{pid}{' &middot; DEMO' if p['demo'] else ''}</p>
<div class="rule"><b>The rule:</b> If total rainfall at {e(p['venue'])} between {start:%I:%M %p} and {end:%I:%M %p}
on {start:%d %b %Y} is <b>{p['threshold_mm']:g} mm or more</b>, pay <b>{trigger.inr(p['payout_amount'])}</b>
to {e(p['paypal_email'])} automatically. No claim needed.</div>
<table><tr><td>Organiser</td><td>{e(p['user_name'])}</td></tr><tr><td>Event</td><td>{e(p['event_name'])}</td></tr>
<tr><td>Location</td><td>{p['lat']:.4f}, {p['lon']:.4f}</td></tr><tr><td>Premium paid</td><td>{trigger.inr(p['premium'])}</td></tr>
<tr><td>Estimated chance of trigger</td><td>{p['probability']*100:.1f}%</td></tr>
<tr><td>Weather sources</td><td>ECMWF ERA5 + NOAA GFS (via Open-Meteo)</td></tr>
<tr><td>PayPal capture</td><td>{e(prem['paypal_id'] if prem else '-')}</td></tr><tr><td>Issued</td><td>{e(p['created_at'])}</td></tr></table>
<p style="font-size:12px;color:#5a6b75">Hackathon prototype. Not an insurance product. A real launch needs a licensed insurer partner (IRDAI).</p>
<button onclick="print()">Print / Save as PDF</button></body></html>"""


# ------------------------------------------------------------------ webhooks
@app.post("/api/webhooks/paypal")
async def webhook(request: Request):
    event = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not await asyncio.to_thread(paypal.verify_webhook, headers, event):
        raise HTTPException(400, "Webhook signature could not be verified")
    kind, res = event.get("event_type", ""), event.get("resource", {})
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        pid = res.get("custom_id")
        order_id = res.get("supplementary_data", {}).get("related_ids", {}).get("order_id", "")
        if pid and trigger.load(int(pid)):
            _activate(int(pid), order_id, res.get("id"), "COMPLETED", {"webhook": kind})
    elif kind.startswith("PAYMENT.PAYOUTS-ITEM.") or kind.startswith("PAYMENT.PAYOUTSBATCH."):
        batch = res.get("payout_batch_id") or res.get("batch_header", {}).get("payout_batch_id")
        status = "SUCCESS" if kind in ("PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "PAYMENT.PAYOUTSBATCH.SUCCESS") else kind.split(".")[-1]
        row = db.one("SELECT policy_id FROM payments WHERE paypal_id = ? AND type = 'PAYOUT'", batch)
        if row:
            db.run("UPDATE payments SET status = ? WHERE paypal_id = ?", status, batch)
            if status == "SUCCESS":
                db.set_status(row["policy_id"], "PAID")
    return {"ok": True}


# ------------------------------------------------------------------ admin
@app.get("/api/admin")
def admin():
    rows = db.all_("""SELECT p.id, p.status, p.threshold_mm, p.payout_amount, p.premium, p.probability, p.demo,
                             p.decision_json, e.name AS event_name, e.venue, e.start_time, u.name AS user_name
                      FROM policies p JOIN events e ON e.id = p.event_id JOIN users u ON u.id = e.user_id
                      ORDER BY p.id DESC""")
    for r in rows:
        r["decision"] = json.loads(r.pop("decision_json")) if r["decision_json"] else None
    paid = [r for r in rows if r["status"] != "QUOTED"]
    return {
        "policies": rows,
        "totals": {
            "premiums_in_inr": sum(r["premium"] for r in paid),
            "payouts_out_inr": sum(r["payout_amount"] for r in rows if r["status"] in ("PAID", "TRIGGERED")),
            "expected_payouts_inr": round(sum(r["probability"] * r["payout_amount"] for r in paid)),
            "active": sum(r["status"] == "ACTIVE" for r in rows),
            "flagged": sum(r["status"] == "FLAGGED" for r in rows),
        },
        "model": pricing.metrics(),
        "mock_paypal": paypal.mock,
    }


@app.post("/api/admin/policies/{pid}/resolve")
def resolve(pid: int, body: ResolveIn):
    p = _policy_or_404(pid)
    if p["status"] != "FLAGGED":
        raise HTTPException(409, "Only flagged policies need review")
    if body.decision == "pay":
        db.set_status(pid, "TRIGGERED", summary=(p["summary"] or "") + " Reviewed: payout approved.")
        trigger.pay(pid)
    elif body.decision == "reject":
        db.set_status(pid, "EXPIRED", summary="After review, the rain did not meet the agreed rule. No payout.")
    else:
        raise HTTPException(400, "decision must be 'pay' or 'reject'")
    return get_policy(pid)
