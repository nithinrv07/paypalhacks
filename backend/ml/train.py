"""Train the EventRain risk model.

Question the model answers:
    "Will total rain in this event window be >= threshold mm?"  -> probability

Data: 15 years (2010-2024) of hourly ERA5 rainfall for 4 points around Chennai.
Each past day becomes many training rows (different start times, durations and
thresholds), labelled 1 if the window really crossed the threshold.

Features
    doy_sin/doy_cos      season (NE monsoon peaks Oct-Dec)
    hour_sin/hour_cos    time of day the event starts
    duration_h           longer events = more exposure
    log_threshold        higher threshold = rarer
    base_rate            local climatology: share of days within +-7 days of this
                         date (other years only) with daily rain >= threshold
    log_base_rate

We compare Logistic Regression with Gradient Boosting on held-out years
(2023-2024) using the Brier score and a calibration table, and save the better one.

Run:  python -m ml.train        (from the backend folder; takes 1-3 minutes)
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.weather import _get, ARCHIVE

OUT = Path(__file__).parent
POINTS = {  # spread over Chennai
    "Besant Nagar": (13.00, 80.27),
    "Anna University": (13.01, 80.235),
    "Tambaram": (12.92, 80.12),
    "Anna Nagar": (13.09, 80.21),
}
YEARS = range(2010, 2025)
TEST_YEARS = {2023, 2024}
START_HOURS = [9, 12, 16, 18]
DURATIONS = [3, 4, 6]
THRESHOLDS = [5.0, 10.0, 20.0]
FEATURES = ["doy_sin", "doy_cos", "hour_sin", "hour_cos", "duration_h",
            "log_threshold", "base_rate", "log_base_rate"]


def features(day: date, start_hour: int, duration_h: float, threshold: float, base_rate: float) -> list[float]:
    doy = day.timetuple().tm_yday
    return [math.sin(2 * math.pi * doy / 365.25), math.cos(2 * math.pi * doy / 365.25),
            math.sin(2 * math.pi * start_hour / 24), math.cos(2 * math.pi * start_hour / 24),
            duration_h, math.log(threshold), base_rate, math.log(base_rate + 0.01)]


def load_point(lat: float, lon: float):
    cache = OUT / "data" / f"era5_{lat}_{lon}_{YEARS[0]}_{YEARS[-1]}.json"
    if cache.exists():
        d = json.loads(cache.read_text())
    else:
        print(f"  downloading {lat},{lon} ...", flush=True)
        d = _get(ARCHIVE, latitude=lat, longitude=lon, start_date=f"{YEARS[0]}-01-01",
                 end_date=f"{YEARS[-1]}-12-31", hourly="precipitation", models="era5")
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps({"hourly": d["hourly"]}))
    hourly: dict[date, list[float]] = defaultdict(lambda: [0.0] * 24)
    for t, p in zip(d["hourly"]["time"], d["hourly"]["precipitation"]):
        hourly[date.fromisoformat(t[:10])][int(t[11:13])] = p or 0.0
    return hourly


def base_rates(daily: dict[date, float], day: date, thresholds, window=7):
    """Leave-one-year-out climatology so the feature never sees the label's year."""
    out = {}
    for th in thresholds:
        hits = total = 0
        for y in YEARS:
            if y == day.year:
                continue
            try:
                c = day.replace(year=y)
            except ValueError:
                c = day.replace(year=y, day=28)
            for k in range(-window, window + 1):
                v = daily.get(c + timedelta(days=k))
                if v is not None:
                    hits += v >= th
                    total += 1
        out[th] = hits / total if total else 0.0
    return out


def build():
    """Preallocated numpy arrays - this machine has little free RAM."""
    per_day = len(START_HOURS) * len(DURATIONS) * len(THRESHOLDS)
    chunks = []
    for name, (lat, lon) in POINTS.items():
        hourly = load_point(lat, lon)
        daily = {d: sum(h) for d, h in hourly.items()}
        n = len(hourly) * per_day
        X = np.empty((n, len(FEATURES)), dtype=np.float32)
        y = np.empty(n, dtype=np.int8)
        yr = np.empty(n, dtype=np.int16)
        i = 0
        for day, hrs in hourly.items():
            br = base_rates(daily, day, THRESHOLDS)
            for sh in START_HOURS:
                for dur in DURATIONS:
                    rain = sum(hrs[sh:sh + dur])
                    for th in THRESHOLDS:
                        X[i] = features(day, sh, dur, th, br[th])
                        y[i] = rain >= th
                        yr[i] = day.year
                        i += 1
        chunks.append((X, y, yr))
        del hourly, daily
        print(f"  {name}: {n:,} rows", flush=True)
    return (np.concatenate([c[0] for c in chunks]), np.concatenate([c[1] for c in chunks]),
            np.concatenate([c[2] for c in chunks]))


def calibration(y, p, bins=10):
    rows = []
    edges = np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 30:
            rows.append({"predicted": round(float(p[m].mean()), 3),
                         "actual": round(float(y[m].mean()), 3), "n": int(m.sum())})
    return rows


def main():
    print("Building dataset from Open-Meteo ERA5 ...")
    X, y, yr = build()
    test = np.isin(yr, list(TEST_YEARS))
    Xtr, ytr, Xte, yte = X[~test], y[~test], X[test], y[test]
    print(f"rows: train={len(ytr):,} test={len(yte):,}  positive rate={y.mean():.3f}")

    candidates = {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        "gradient_boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                                            max_leaf_nodes=31, random_state=0),
    }
    climo_brier = brier_score_loss(yte, np.clip(Xte[:, FEATURES.index("base_rate")], 0, 1))
    results = {}
    rng = np.random.default_rng(0)
    sub = rng.choice(len(ytr), size=min(len(ytr), 250_000), replace=False)  # boosting needs less RAM
    for name, model in candidates.items():
        if name == "gradient_boosting":
            model.fit(Xtr[sub], ytr[sub])
        else:
            model.fit(Xtr, ytr)
        p = model.predict_proba(Xte)[:, 1]
        results[name] = {"brier": round(float(brier_score_loss(yte, p)), 5),
                         "auc": round(float(roc_auc_score(yte, p)), 4),
                         "calibration": calibration(yte, p)}
        print(f"{name:22s} brier={results[name]['brier']:.5f} auc={results[name]['auc']:.4f}")
    print(f"{'climatology only':22s} brier={climo_brier:.5f}")

    best = min(results, key=lambda k: results[k]["brier"])
    joblib.dump({"model": candidates[best], "features": FEATURES, "name": best}, OUT / "model.joblib")
    metrics = {"chosen": best, "models": results, "climatology_brier": round(float(climo_brier), 5),
               "train_years": f"{YEARS[0]}-{min(TEST_YEARS) - 1}", "test_years": sorted(TEST_YEARS),
               "rows_train": int(len(ytr)), "rows_test": int(len(yte)), "points": list(POINTS)}
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"saved {best} -> ml/model.joblib")


if __name__ == "__main__":
    main()
