"""EventRain Cover API.

Run:  uvicorn app.main:app --reload --port 8000   (from the backend folder)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, EmailStr, Field, model_validator

from . import config, db, pricing, tiers, trigger
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
    payout_mode: Literal["fixed", "graduated"] = "fixed"

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


class Split(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: EmailStr
    pct: float = Field(gt=0, le=100)


class PolicyIn(QuoteIn):
    venue: str = Field(min_length=2, max_length=120)
    event_name: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    paypal_email: EmailStr
    splits: list[Split] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def split_rules(self):
        if self.splits and abs(sum(x.pct for x in self.splits) - 100) > 0.01:
            raise ValueError("Payout split percentages must add up to 100")
        return self


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
        return pricing.quote(q.lat, q.lon, q.start, q.end, q.threshold_mm, q.payout_inr, q.payout_mode, q.demo)
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
    q = pricing.quote(p.lat, p.lon, p.start, p.end, p.threshold_mm, p.payout_inr, p.payout_mode, p.demo,
                      suggest=False)  # price on the server, never trust the client
    splits = [x.model_dump() for x in p.splits] or [{"name": p.name, "email": p.paypal_email, "pct": 100.0}]
    uid = db.run("INSERT INTO users (name, email, paypal_email) VALUES (?,?,?)", p.name, p.email, p.paypal_email)
    eid = db.run("INSERT INTO events (user_id, name, venue, lat, lon, start_time, end_time) VALUES (?,?,?,?,?,?,?)",
                 uid, p.event_name, p.venue, p.lat, p.lon, p.start.isoformat(), p.end.isoformat())
    pid = db.run("""INSERT INTO policies (event_id, threshold_mm, payout_amount, premium, probability, status,
                    quote_json, demo, demo_scenario, payout_mode, splits_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 eid, q["threshold_mm"], p.payout_inr, q["premium_inr"], q["probability"], "QUOTED",
                 json.dumps(q), int(p.demo), scenario, p.payout_mode, json.dumps(splits), db.now(), db.now())
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
    out["live"] = trigger.live(p) if p["status"] not in ("QUOTED", "CANCELLED") else None
    out["splits"] = trigger.splits(p)
    out.pop("splits_json", None)
    out["ladder"] = [{"mm": mm, "fraction": f} for mm, f in tiers.ladder(p.get("payout_mode"), p["threshold_mm"])]
    out["can_cancel"] = _can_cancel(p)
    out["refund_inr"] = max(0, p["premium"] - config.PLATFORM_FEE_INR)
    return out


def _can_cancel(p: dict) -> bool:
    """Cancel before the cut-off (or, for demos, before the replay starts)."""
    if p["status"] != "ACTIVE":
        return False
    if p["demo"]:
        return not p["replay_started_at"]
    return datetime.now() < datetime.fromisoformat(p["start_time"]) - timedelta(hours=config.CUTOFF_HOURS)


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


@app.post("/api/policies/{pid}/cancel")
def cancel(pid: int):
    """Cancel for non-weather reasons: refund the premium minus the platform fee
    through the PayPal Refunds API."""
    p = _policy_or_404(pid)
    if not _can_cancel(p):
        raise HTTPException(409, f"Cover can only be cancelled while active and at least "
                                 f"{config.CUTOFF_HOURS:g} hours before the event")
    prem = db.one("SELECT paypal_id FROM payments WHERE policy_id = ? AND type = 'PREMIUM'", pid)
    refund_inr = max(0, p["premium"] - config.PLATFORM_FEE_INR)
    usd = round(refund_inr / config.INR_PER_USD, 2)
    try:
        res = paypal.refund(prem["paypal_id"], usd, f"EventRain Cover #{pid} cancelled")
    except Exception as e:
        raise HTTPException(502, f"PayPal refund failed: {e}")
    db.run("INSERT INTO payments (policy_id, type, paypal_id, amount, currency, status, raw, created_at) "
           "VALUES (?,?,?,?,?,?,?,?)", pid, "REFUND", res["id"], usd, "USD", res["status"],
           json.dumps(res.get("raw", {})), db.now())
    db.set_status(pid, "CANCELLED", summary=f"Cancelled before the event. {trigger.inr(refund_inr)} was refunded to "
                                            f"your PayPal (premium minus the {trigger.inr(config.PLATFORM_FEE_INR)} fee).")
    return get_policy(pid)


def _proof(pid: int) -> dict:
    p = _policy_or_404(pid)
    if not p["decision_json"]:
        raise HTTPException(409, "The proof pack is ready once the weather has been checked")
    decision = json.loads(p["decision_json"])
    rows = db.all_("SELECT source, timestamp, rain_mm FROM weather_readings WHERE policy_id = ? AND source != 'replay' "
                   "ORDER BY source, timestamp", pid)
    readings: dict[str, list] = {}
    for r in rows:
        readings.setdefault(r["source"], []).append({"time": r["timestamp"], "rain_mm": r["rain_mm"]})
    payouts = db.all_("SELECT type, paypal_id, amount, currency, status, raw, created_at FROM payments "
                      "WHERE policy_id = ? ORDER BY id", pid)
    for x in payouts:
        raw_text = x.pop("raw") or ""
        try:
            raw = json.loads(raw_text) if raw_text.startswith("{") else {}
        except ValueError:
            raw = {}
        x["recipients"] = raw.get("items")
    evidence = {"policy_id": pid, "venue": p["venue"], "lat": p["lat"], "lon": p["lon"],
                "event_window": [p["start_time"], p["end_time"]], "weather_window": decision["window"],
                "payout_mode": p.get("payout_mode") or "fixed",
                "ladder": decision.get("ladder") or [[p["threshold_mm"], 1.0]],
                "cover_inr": p["payout_amount"], "readings": readings, "decision": decision}
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    return {**evidence, "payments": payouts, "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "generated_at": db.now(),
            "how_to_verify": "Open each URL in decision.sources: the hourly precipitation for the weather window "
                             "must match readings. Recompute sha256 over the evidence fields (sorted keys, no spaces)."}


@app.get("/api/policies/{pid}/proof.json")
def proof_json(pid: int):
    return JSONResponse(_proof(pid), headers={"Content-Disposition": f'attachment; filename="eventrain-proof-{pid}.json"'})


@app.get("/api/policies/{pid}/proof", response_class=HTMLResponse)
def proof_page(pid: int):
    pf = _proof(pid)
    d = pf["decision"]
    e = lambda x: escape(str(x))
    srcs = list(pf["readings"])
    times = sorted({r["time"] for rows in pf["readings"].values() for r in rows})
    look = {s: {r["time"]: r["rain_mm"] for r in pf["readings"][s]} for s in srcs}
    run = {s: 0.0 for s in srcs}
    body_rows = []
    for t in times:
        cells = []
        for s in srcs:
            v = look[s].get(t, 0.0)
            run[s] += v
            cells.append(f"<td>{v:.2f}</td><td class=m>{run[s]:.2f}</td>")
        body_rows.append(f"<tr><td>{e(t.replace('T', ' '))}</td>{''.join(cells)}</tr>")
    head = "".join(f"<th>{e(s)}<br><small>mm / hour</small></th><th class=m>running total</th>" for s in srcs)
    totals = "".join(f"<td><b>{d['totals'].get(s, 0):.2f}</b></td><td></td>" for s in srcs)
    ladder = ", ".join(f"{trigger.inr(pf['cover_inr'] * f)} at {mm:g} mm" for mm, f in pf["ladder"])
    links = "".join(f"<li><b>{e(k)}</b>: <a href='{e(v)}' target=_blank>{e(v)}</a></li>"
                    for k, v in (d.get("sources") or {}).items())
    pays = "".join(f"<li>{e(x['type'])} &middot; ${x['amount']:.2f} &middot; {e(x['status'])} &middot; <code>{e(x['paypal_id'])}</code>"
                   + ("".join(f"<br>&nbsp;&nbsp;&rarr; {e(r['name'])} &lt;{e(r['email'])}&gt; ₹{r.get('amount_inr', 0):,}"
                              for r in (x.get("recipients") or [])) if x.get("recipients") else "") + "</li>"
                   for x in pf["payments"])
    outcome = {"PAY": "Payout rule met", "NO_PAY": "Rule not met: no payout", "REVIEW": "Sent to human review"}
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Proof pack #{pid}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#0b1e2a}}
h1{{margin:0}}.muted{{color:#5b7380}}table{{border-collapse:collapse;width:100%;font-size:14px;margin:12px 0}}
th,td{{padding:6px 8px;border-bottom:1px solid #dce7ec;text-align:right}}th:first-child,td:first-child{{text-align:left}}
.m{{color:#5b7380}}.box{{background:#eef6f9;border-left:4px solid #0e4f6e;padding:12px 16px;margin:16px 0}}
code{{font-size:12px;word-break:break-all}}a{{word-break:break-all}}@media print{{.np{{display:none}}}}</style></head><body>
<h1>EventRain proof pack</h1><p class=muted>Policy #{pid} &middot; {e(pf['venue'])} ({pf['lat']:.4f}, {pf['lon']:.4f})
{' &middot; DEMO replay' if d.get('demo_replay') else ''}</p>
<div class=box><b>Rule:</b> rain in {e(d['window'][0].replace('T', ' '))} &rarr; {e(d['window'][1][11:16])} pays {ladder}.<br>
<b>Decision:</b> {outcome.get(d['outcome'], d['outcome'])}. {e(d['reason'])}.<br>
<b>Share of cover earned:</b> {int(d.get('earned_fraction', 1 if d['outcome'] == 'PAY' else 0) * 100)}%
{f" (+{int(d['disputed_fraction'] * 100)}% under review)" if d.get('disputed_fraction') else ''}
{f"<br><b>Note:</b> {d['forecast_hours']} of {d['hours']} hours were still in the future; the latest forecast was used." if d.get('forecast_hours') else ''}</div>
<h2>Hourly rainfall from both independent sources</h2>
<table><thead><tr><th>Hour</th>{head}</tr></thead><tbody>{''.join(body_rows)}
<tr><td><b>Total</b></td>{totals}</tr></tbody></table>
<p class=muted>Two sources may disagree by up to {d['tolerance_mm']:.1f} mm before a person reviews. Spread here: {d['spread_mm']} mm.</p>
<h2>Check it yourself</h2><ul>{links}</ul>
<h2>PayPal trail</h2><ul>{pays}</ul>
<h2>Fingerprint</h2><p>SHA-256 of the evidence: <code>{pf['sha256']}</code></p>
<p class=np><a href="/api/policies/{pid}/proof.json">Download proof.json</a> &middot; <button onclick="print()">Print / Save as PDF</button></p>
<p class=muted style="font-size:12px">Generated {e(pf['generated_at'])}. Hackathon prototype, not an insurance product.</p></body></html>"""


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
on {start:%d %b %Y} reaches the agreed level, pay <b>{tiers.describe(p.get('payout_mode'), p['threshold_mm'], p['payout_amount'], trigger.inr)}</b>
automatically, split as: {e(', '.join(f"{x['name']} {x['pct']:g}%" for x in trigger.splits(p)))}. No claim needed.</div>
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
                             p.payout_mode, p.paid_fraction, p.quote_json,
                             p.decision_json, e.name AS event_name, e.venue, e.start_time, u.name AS user_name
                      FROM policies p JOIN events e ON e.id = p.event_id JOIN users u ON u.id = e.user_id
                      ORDER BY p.id DESC""")
    for r in rows:
        r["decision"] = json.loads(r.pop("decision_json")) if r["decision_json"] else None
        q = json.loads(r.pop("quote_json") or "{}")
        r["expected_fraction"] = q.get("expected_payout_fraction", r["probability"])
    paid = [r for r in rows if r["status"] not in ("QUOTED", "CANCELLED")]
    return {
        "policies": rows,
        "totals": {
            "premiums_in_inr": sum(r["premium"] for r in paid),
            "payouts_out_inr": round(sum((r["paid_fraction"] or 0) * r["payout_amount"] for r in rows)),
            "expected_payouts_inr": round(sum(r["expected_fraction"] * r["payout_amount"] for r in paid)),
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
    d = json.loads(p["decision_json"] or "{}")
    if body.decision == "pay":  # approve the disputed part on top of what was already paid
        target = (p.get("paid_fraction") or 0) + d.get("disputed_fraction", 1.0)
        db.set_status(pid, "TRIGGERED", summary=(p["summary"] or "") + " Reviewed: the rest of the payout was approved.")
        with trigger._check_lock:
            if trigger.pay_to(pid, min(1.0, target)):
                db.set_status(pid, "PAID")
    elif body.decision == "reject":
        if p.get("paid_fraction"):
            db.set_status(pid, "PAID", summary=(p["summary"] or "") + " Reviewed: only the part both sources confirmed is paid.")
        else:
            db.set_status(pid, "EXPIRED", summary="After review, the rain did not meet the agreed rule. No payout.")
    else:
        raise HTTPException(400, "decision must be 'pay' or 'reject'")
    return get_policy(pid)
