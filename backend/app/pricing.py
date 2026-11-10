"""AI risk pricing: probability of rain >= threshold during the event -> premium."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import joblib

from . import config, weather
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


def quote(lat: float, lon: float, start: datetime, end: datetime, threshold_mm: float,
          payout_inr: float) -> dict:
    duration_h = (end - start).total_seconds() / 3600
    climo = weather.climatology(lat, lon, start.date(), threshold_mm)

    # 1) historical model (works for any date, any lead time)
    m = model()
    x = features(start.date(), start.hour, duration_h, threshold_mm, climo["base_rate"])
    p_hist = float(m["model"].predict_proba([x])[0, 1])

    # 2) live ensemble forecast (only within ~2 weeks)
    ens = weather.ensemble_probability(lat, lon, start, end, threshold_mm)
    if ens:
        w = max(0.0, 0.8 * (1 - ens["lead_days"] / 14))  # trust forecast more as date nears
        p = w * ens["probability"] + (1 - w) * p_hist
    else:
        w, p = 0.0, p_hist
    p = min(max(p, 0.01), 0.95)

    expected_loss = p * payout_inr
    with_margin = expected_loss * (1 + config.MARGIN)
    premium = round(with_margin + config.PLATFORM_FEE_INR)

    return {
        "probability": round(p, 4),
        "premium_inr": premium,
        "payout_inr": payout_inr,
        "threshold_mm": threshold_mm,
        "premium_usd": round(premium / config.INR_PER_USD, 2),
        "payout_usd": round(payout_inr / config.INR_PER_USD, 2),
        "breakdown": {
            "expected_loss_inr": round(expected_loss),
            "margin_pct": config.MARGIN * 100,
            "margin_inr": round(with_margin - expected_loss),
            "platform_fee_inr": config.PLATFORM_FEE_INR,
        },
        "signals": {
            "model": m["name"],
            "historical_probability": round(p_hist, 4),
            "forecast": ens,
            "forecast_weight": round(w, 2),
            "local_base_rate": round(climo["base_rate"], 4),
        },
        "history": climo,
        "duration_h": duration_h,
    }
