"""Trigger Checker: after the event, compare measured rain with the agreed rule
using two independent sources, then pay automatically (or flag for review)."""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta

from . import config, db, weather
from .paypal import paypal


# ----------------------------------------------------------------- helpers
def load(policy_id: int) -> dict | None:
    return db.one("""SELECT p.*, e.name AS event_name, e.venue, e.lat, e.lon, e.start_time, e.end_time,
                            u.name AS user_name, u.email, u.paypal_email
                     FROM policies p JOIN events e ON e.id = p.event_id JOIN users u ON u.id = e.user_id
                     WHERE p.id = ?""", policy_id)


def _live_window(p: dict) -> tuple[datetime, datetime]:
    """Live demo.
    Event today or tomorrow: its own real hours (measured where they have passed,
    latest forecast where they haven't).
    Event later: the most recent finished occurrence of its clock hours (today if
    already over, else yesterday), measured from when the replay started so the
    trigger check later reads exactly the same hours."""
    start, end = datetime.fromisoformat(p["start_time"]), datetime.fromisoformat(p["end_time"])
    if 0 <= (start.date() - date.today()).days <= 1:
        return start, end
    ref = datetime.fromisoformat(p["replay_started_at"]) if p.get("replay_started_at") else datetime.now()
    ref = ref.replace(minute=0, second=0, microsecond=0)
    w1 = datetime.combine(ref.date(), end.time())
    if w1 > ref:
        w1 -= timedelta(days=1)
    return w1 - (end - start), w1


def weather_window(p: dict) -> tuple[datetime, datetime]:
    """The window whose weather decides the policy. Demo policies replay real
    weather from other hours instead of the future event date:
      rain - a heavy-rain evening (15 Nov 2023), pays out
      dry  - a drizzle-only evening (26 Nov 2023), no payout
      live - the latest real weather at the venue, outcome unknown in advance"""
    start, end = datetime.fromisoformat(p["start_time"]), datetime.fromisoformat(p["end_time"])
    if p["demo"]:
        if p.get("demo_scenario") == "live":
            return _live_window(p)
        r = date.fromisoformat(config.DEMO_DRY_DATE if p.get("demo_scenario") == "dry" else config.DEMO_REPLAY_DATE)
        shift = datetime.combine(r, start.time()) - start
        return start + shift, end + shift
    return start, end


def is_forecast(hour_iso: str, at: datetime) -> bool:
    """An hour still in the future at time `at` has only a forecast, not a measurement."""
    return datetime.fromisoformat(hour_iso) + timedelta(hours=1) > at


def replay_date(p: dict) -> str:
    return weather_window(p)[0].date().isoformat()


def inr(x: float) -> str:
    s = f"{int(round(x)):d}"
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts) + "," + tail


# ----------------------------------------------------------------- live status
_live_cache: dict[int, tuple[float, list[dict]]] = {}


def live(p: dict) -> dict:
    """What the organiser sees during the event: rain so far vs threshold."""
    th = p["threshold_mm"]
    w0, w1 = weather_window(p)
    if p["demo"]:
        if not p["replay_started_at"]:
            return {"mode": "demo", "started": False, "rain_so_far": 0.0, "threshold_mm": th, "series": [],
                    "replay_date": replay_date(p), "scenario": p.get("demo_scenario") or "rain"}
        rows = db.all_("SELECT timestamp, rain_mm FROM weather_readings WHERE policy_id = ? AND source = 'replay' "
                       "ORDER BY timestamp", p["id"])
        elapsed = (datetime.now() - datetime.fromisoformat(p["replay_started_at"])).total_seconds()
        frac = min(1.0, elapsed / config.DEMO_REPLAY_SECONDS)
        hours = frac * len(rows)
        series, total = [], 0.0
        started = datetime.fromisoformat(p["replay_started_at"])
        for i, r in enumerate(rows):
            if i >= hours:
                break
            part = min(1.0, hours - i)
            total += r["rain_mm"] * part
            series.append({"time": r["timestamp"][11:16], "rain_mm": round(r["rain_mm"] * part, 2),
                           "cumulative": round(total, 2),
                           "forecast": is_forecast(r["timestamp"], started)})
        clock = w0 + timedelta(hours=hours)
        return {"mode": "demo", "started": True, "finished": frac >= 1, "progress": round(frac, 3),
                "replay_date": replay_date(p), "scenario": p.get("demo_scenario") or "rain", "clock": clock.strftime("%H:%M"),
                "rain_so_far": round(total, 2), "threshold_mm": th, "series": series,
                "forecast_hours": sum(is_forecast(r["timestamp"], started) for r in rows)}

    now = datetime.now()
    if now < w0:
        return {"mode": "live", "started": False, "rain_so_far": 0.0, "threshold_mm": th, "series": [],
                "starts_in_s": int((w0 - now).total_seconds())}
    cached = _live_cache.get(p["id"])
    if not cached or time.time() - cached[0] > 600:
        obs = weather.observed_hourly(p["lat"], p["lon"], w0, min(now, w1))
        _live_cache[p["id"]] = (time.time(), next(iter(obs.values()), []))
    series, total = [], 0.0
    for r in _live_cache[p["id"]][1]:
        total += r["rain_mm"]
        series.append({"time": r["time"][11:16], "rain_mm": r["rain_mm"], "cumulative": round(total, 2)})
    return {"mode": "live", "started": True, "finished": now >= w1, "rain_so_far": round(total, 2),
            "threshold_mm": th, "series": series}


def start_replay(policy_id: int):
    p = load(policy_id)
    w0, w1 = weather_window(p)
    # The gauge shows the first source; the trigger check later reads both
    obs = weather.observed_hourly(p["lat"], p["lon"], w0, w1)
    rows = next(iter(obs.values()), [])
    db.run("DELETE FROM weather_readings WHERE policy_id = ? AND source = 'replay'", policy_id)
    for r in rows:
        db.run("INSERT INTO weather_readings (policy_id, source, timestamp, rain_mm) VALUES (?,?,?,?)",
               policy_id, "replay", r["time"], r["rain_mm"])
    db.run("UPDATE policies SET replay_started_at = ?, updated_at = ? WHERE id = ?", db.now(), db.now(), policy_id)


# ----------------------------------------------------------------- the check
_check_lock = threading.Lock()


def check(policy_id: int, force: bool = False) -> dict:
    """One check at a time: the scheduler and the page may both ask at once."""
    with _check_lock:
        return _check(policy_id, force)


def _check(policy_id: int, force: bool = False) -> dict:
    p = load(policy_id)
    if p["status"] != "ACTIVE" and not force:
        return {"status": p["status"], "message": "Policy is not active"}
    w0, w1 = weather_window(p)
    th = p["threshold_mm"]
    obs = weather.observed_hourly(p["lat"], p["lon"], w0, w1)
    if len(obs) < 2:
        return {"status": p["status"], "message": "Waiting for both weather sources"}

    db.run("DELETE FROM weather_readings WHERE policy_id = ? AND source != 'replay'", policy_id)
    for src, rows in obs.items():
        for r in rows:
            db.run("INSERT INTO weather_readings (policy_id, source, timestamp, rain_mm) VALUES (?,?,?,?)",
                   policy_id, src, r["time"], r["rain_mm"])

    totals = {src: round(sum(r["rain_mm"] for r in rows), 2) for src, rows in obs.items()}
    vals = list(totals.values())
    met = [v >= th for v in vals]
    tolerance = max(2.0, 0.3 * th)  # how far apart the two sources may be
    spread = round(max(vals) - min(vals), 2)
    if all(met) or not any(met):
        outcome, reason = ("PAY" if all(met) else "NO_PAY"), "Both sources agree"
    elif spread <= tolerance:
        mean = sum(vals) / len(vals)
        outcome = "PAY" if mean >= th else "NO_PAY"
        reason = f"Sources differ slightly ({spread} mm); decided on the average ({mean:.1f} mm)"
    else:
        outcome, reason = "REVIEW", f"Sources disagree by {spread} mm (> {tolerance:.1f} mm): flagged for human review"

    rain = round(sum(vals) / len(vals), 1)
    checked_at = datetime.fromisoformat(p["replay_started_at"]) if p.get("replay_started_at") else datetime.now()
    hours_in_window = obs[next(iter(obs))]
    forecast_hours = sum(is_forecast(r["time"], checked_at) for r in hours_in_window)
    fc_note = (f" Note: {forecast_hours} of the {len(hours_in_window)} hours had not happened yet, so the latest "
               f"forecast was used for them.") if forecast_hours else ""
    hourly = obs[next(iter(obs))]
    peak = max(hourly, key=lambda r: r["rain_mm"]) if hourly else None
    decision = {"totals": totals, "threshold_mm": th, "outcome": outcome, "reason": reason,
                "spread_mm": spread, "tolerance_mm": tolerance, "window": [w0.isoformat(), w1.isoformat()],
                "checked_at": db.now(), "demo_replay": bool(p["demo"]),
                "forecast_hours": forecast_hours, "hours": len(hours_in_window)}

    if outcome == "PAY":
        summary = (f"It rained {rain} mm at {p['venue']} between {w0.strftime('%I %p').lstrip('0')} and {w1.strftime('%I %p').lstrip('0')}"
                   f"{' (peak ' + str(peak['rain_mm']) + ' mm around ' + peak['time'][11:16] + ')' if peak else ''}. "
                   f"Your threshold was {th:g} mm, so {inr(p['payout_amount'])} has been sent to your PayPal "
                   f"({p['paypal_email']}). No claim needed.{fc_note}")
        db.set_status(policy_id, "TRIGGERED", decision_json=json.dumps(decision), summary=summary)
        pay(policy_id)
    elif outcome == "NO_PAY":
        summary = (f"Good weather! Only {rain} mm of rain fell at {p['venue']} during your event "
                   f"(threshold {th:g} mm), so no payout was needed. We hope the event went well.{fc_note}")
        db.set_status(policy_id, "EXPIRED", decision_json=json.dumps(decision), summary=summary)
    else:
        summary = ("The two weather sources disagree about how much rain fell, so a person is double-checking. "
                   "You don't need to do anything.")
        db.set_status(policy_id, "FLAGGED", decision_json=json.dumps(decision), summary=summary)
    return {"status": load(policy_id)["status"], "decision": decision, "summary": summary}


def pay(policy_id: int):
    p = load(policy_id)
    if db.one("SELECT id FROM payments WHERE policy_id = ? AND type = 'PAYOUT'", policy_id):
        return  # idempotent: never pay twice
    usd = round(p["payout_amount"] / config.INR_PER_USD, 2)
    note = p["summary"] or f"EventRain Cover payout for {p['event_name']}"
    try:
        res = paypal.send_payout(p["paypal_email"], usd, policy_id, note)
    except Exception as e:  # keep TRIGGERED so the loop/admin can retry
        db.run("INSERT INTO payments (policy_id, type, paypal_id, amount, currency, status, raw, created_at) "
               "VALUES (?,?,?,?,?,?,?,?)", policy_id, "PAYOUT_ERROR", None, usd, "USD", "FAILED", str(e), db.now())
        return
    db.run("INSERT INTO payments (policy_id, type, paypal_id, amount, currency, status, raw, created_at) "
           "VALUES (?,?,?,?,?,?,?,?)", policy_id, "PAYOUT", res["batch_id"], usd, "USD", res["status"],
           json.dumps(res.get("raw", {})), db.now())
    if res["status"] == "SUCCESS":
        db.set_status(policy_id, "PAID")


def refresh_payouts():
    for row in db.all_("SELECT pay.id, pay.policy_id, pay.paypal_id FROM payments pay JOIN policies p "
                       "ON p.id = pay.policy_id WHERE pay.type = 'PAYOUT' AND p.status = 'TRIGGERED'"):
        try:
            status = paypal.payout_status(row["paypal_id"])
        except Exception:
            continue
        db.run("UPDATE payments SET status = ? WHERE id = ?", status, row["id"])
        if status == "SUCCESS":
            db.set_status(row["policy_id"], "PAID")


# ----------------------------------------------------------------- scheduler tick
_last_check: dict[int, float] = {}


def tick():
    """Called every ~10 s by the background loop in main.py."""
    now = datetime.now()
    for p in db.all_("SELECT p.id, p.demo, p.replay_started_at, e.end_time FROM policies p "
                     "JOIN events e ON e.id = p.event_id WHERE p.status = 'ACTIVE'"):
        if p["demo"]:
            due = p["replay_started_at"] and (now - datetime.fromisoformat(p["replay_started_at"])
                                              ).total_seconds() >= config.DEMO_REPLAY_SECONDS
        else:  # give weather data an hour to settle; retry at most every 30 min
            due = now >= datetime.fromisoformat(p["end_time"]) + timedelta(hours=1) and \
                time.time() - _last_check.get(p["id"], 0) > 1800
        if due:
            _last_check[p["id"]] = time.time()
            try:
                check(p["id"])
            except Exception as e:
                print(f"trigger check failed for policy {p['id']}: {e}")
    refresh_payouts()
