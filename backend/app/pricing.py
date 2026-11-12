"""AI risk pricing.

For each payout level (rain >= X mm during the event) we estimate a probability
by blending a model trained on 15 years of history with the live 31-member GFS
ensemble forecast. The premium is the expected payout plus margin and fee.

Also: the Reschedule Suggester (cheaper nearby slots) and an hour-by-hour risk
strip for the chosen day.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import joblib

from . import config, tiers, weather
from ml.train import features

ML_DIR = Path(__file__).resolve().parents[1] / "ml"
_model = None


def model():
    global _model
    if _model is None:
        path = ML_DIR / "model.joblib"
        if not path.exists():
            raise RuntimeError("Model not trained yet. Run: python -m ml.train")
        _model = joblib.load(path)
    return _model


def metrics() -> dict:
    p = ML_DIR / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


def probability(lat: float, lon: float, start: datetime, end: datetime, threshold_mm: float) -> dict:
    """P(rain in [start, end) >= threshold) with the signals behind it."""
    duration_h = (end - start).total_seconds() / 3600
    climo = weather.climatology(lat, lon, start.date(), threshold_mm)
    m = model()
    x = features(start.date(), start.hour, duration_h, threshold_mm, climo["base_rate"])
    p_hist = float(m["model"].predict_proba([x])[0, 1])
    ens = weather.ensemble_probability(lat, lon, start, end, threshold_mm)
    if ens:
        w = max(0.0, 0.8 * (1 - ens["lead_days"] / 14))  # trust the forecast more as the date nears
        p = w * ens["probability"] + (1 - w) * p_hist
    else:
        w, p = 0.0, p_hist
    return {"p": min(max(p, 0.01), 0.95), "p_hist": p_hist, "ens": ens, "w": w, "climo": climo,
            "model": m["name"]}


def _price(lat, lon, start, end, threshold_mm, payout_inr, mode) -> dict:
    steps = tiers.ladder(mode, threshold_mm)
    probs, prev = [], 1.0
    for mm, _ in steps:  # heavier rain can never be likelier than lighter rain
        pr = probability(lat, lon, start, end, mm)
        pr["p"] = min(pr["p"], prev)
        prev = pr["p"]
        probs.append(pr)
    # Expected share of cover paid = sum of (step increase x chance of reaching it)
    expected_fraction, last = 0.0, 0.0
    for (mm, frac), pr in zip(steps, probs):
        expected_fraction += (frac - last) * pr["p"]
        last = frac
    expected_loss = expected_fraction * payout_inr
    with_margin = expected_loss * (1 + config.MARGIN)
    premium = round(with_margin + config.PLATFORM_FEE_INR)
    return {"steps": steps, "probs": probs, "expected_fraction": expected_fraction,
            "expected_loss": expected_loss, "with_margin": with_margin, "premium": premium}


def quote(lat: float, lon: float, start: datetime, end: datetime, threshold_mm: float,
          payout_inr: float, mode: str = "fixed", demo: bool = False, suggest: bool = True) -> dict:
    pr = _price(lat, lon, start, end, threshold_mm, payout_inr, mode)
    main = pr["probs"][0] if mode == "graduated" else pr["probs"][-1]  # chance of any payout
    shown_th = pr["steps"][0][0]
    out = {
        "probability": round(main["p"], 4),          # chance of getting any payout
        "expected_payout_fraction": round(pr["expected_fraction"], 4),
        "premium_inr": pr["premium"],
        "payout_inr": payout_inr,
        "threshold_mm": shown_th,
        "payout_mode": mode,
        "tiers": [{"mm": mm, "fraction": f, "probability": round(p["p"], 4)}
                  for (mm, f), p in zip(pr["steps"], pr["probs"])],
        "premium_usd": round(pr["premium"] / config.INR_PER_USD, 2),
        "payout_usd": round(payout_inr / config.INR_PER_USD, 2),
        "breakdown": {
            "expected_loss_inr": round(pr["expected_loss"]),
            "margin_pct": config.MARGIN * 100,
            "margin_inr": round(pr["with_margin"] - pr["expected_loss"]),
            "platform_fee_inr": config.PLATFORM_FEE_INR,
        },
        "signals": {
            "model": main["model"],
            "historical_probability": round(main["p_hist"], 4),
            "forecast": main["ens"],
            "forecast_weight": round(main["w"], 2),
            "local_base_rate": round(main["climo"]["base_rate"], 4),
        },
        "history": main["climo"],
        "duration_h": (end - start).total_seconds() / 3600,
    }
    if suggest:
        out["suggestions"], out["hourly_risk"] = reschedule(lat, lon, start, end, threshold_mm, payout_inr,
                                                            mode, demo, pr["premium"])
    return out


# --------------------------------------------------------------------------- reschedule suggester
def reschedule(lat, lon, start, end, threshold_mm, payout_inr, mode, demo, current_premium):
    """Try nearby days (same hours) and other start times (same day and length).
    Returns up to 3 cheaper slots (saving >= 10%) and the risk for every start
    hour of the chosen day."""
    dur = end - start
    earliest = datetime.now() + (timedelta(0) if demo else timedelta(hours=config.CUTOFF_HOURS))

    def ok(s: datetime) -> bool:  # bookable now, and over by midnight
        midnight = datetime.combine(s.date() + timedelta(days=1), datetime.min.time())
        return s >= earliest and s + dur <= midnight

    slots: dict[datetime, dict] = {}

    def price(s: datetime) -> dict:
        if s not in slots:
            r = _price(lat, lon, s, s + dur, threshold_mm, payout_inr, mode)
            p_any = r["probs"][0]["p"] if mode == "graduated" else r["probs"][-1]["p"]
            slots[s] = {"start": s.isoformat(), "end": (s + dur).isoformat(), "premium_inr": r["premium"],
                        "probability": round(p_any, 4)}
        return slots[s]

    hourly = []
    for h in range(6, 24 - int(dur.total_seconds() // 3600) + 1):
        s = start.replace(hour=h)
        if ok(s):
            hourly.append({"hour": h, **price(s)})

    candidates = [start + timedelta(days=d) for d in (-3, -2, -1, 1, 2, 3)]
    candidates += [start.replace(hour=x["hour"]) for x in hourly]
    options = []
    for s in candidates:
        if s == start or not ok(s):
            continue
        q = price(s)
        saving = current_premium - q["premium_inr"]
        if saving >= max(50, 0.10 * current_premium):
            options.append({**q, "saving_inr": saving,
                            "kind": "time" if s.date() == start.date() else "date"})
    options.sort(key=lambda o: -o["saving_inr"])
    picked: list[dict] = []
    for o in options:  # skip near-duplicates (start within 2 hours of a picked slot)
        s = datetime.fromisoformat(o["start"])
        if all(abs((s - datetime.fromisoformat(x["start"])).total_seconds()) >= 7200 for x in picked):
            picked.append(o)
        if len(picked) == 3:
            break
    return picked, hourly
