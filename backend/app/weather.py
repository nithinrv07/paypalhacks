"""Weather data from Open-Meteo (free, no API key).

Three uses:
  * climatology  - years of daily/hourly history for a location (pricing + chart)
  * forecast     - ensemble forecast -> real probability of crossing a threshold
  * observed     - rainfall measured during an event, from two independent models
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

import httpx

TZ = "Asia/Kolkata"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HIST_FORECAST = "https://historical-forecast-api.open-meteo.com/v1/forecast"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"

_client = httpx.Client(timeout=60)


def _get(url: str, **params) -> dict:
    r = _client.get(url, params={"timezone": TZ, **params})
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- history
@lru_cache(maxsize=256)
def daily_history(lat: float, lon: float, start: str, end: str) -> dict[str, float]:
    """{'YYYY-MM-DD': precipitation_sum_mm} from ERA5 reanalysis."""
    d = _get(ARCHIVE, latitude=lat, longitude=lon, start_date=start, end_date=end,
             daily="precipitation_sum")
    return {t: (p or 0.0) for t, p in zip(d["daily"]["time"], d["daily"]["precipitation_sum"])}


def hourly_history(lat: float, lon: float, start: str, end: str, model: str | None = None) -> dict[str, float]:
    """{'YYYY-MM-DDTHH:00': mm} hourly precipitation from the archive."""
    params = dict(latitude=lat, longitude=lon, start_date=start, end_date=end, hourly="precipitation")
    if model:
        params["models"] = model
    d = _get(ARCHIVE, **params)
    return {t: (p or 0.0) for t, p in zip(d["hourly"]["time"], d["hourly"]["precipitation"])}


def climatology(lat: float, lon: float, event_day: date, threshold_mm: float, years: int = 10,
                window_days: int = 7) -> dict:
    """How often did a day around this date get >= threshold rain in past years?

    Returns the local base rate (a model feature) and per-year totals for the chart.
    """
    lat, lon = round(lat, 2), round(lon, 2)
    last_year = min(date.today().year - 1, event_day.year - 1)
    first_year = last_year - years + 1
    hist = daily_history(lat, lon, f"{first_year}-01-01", f"{last_year}-12-31")
    hits = total = 0
    per_year = []
    for y in range(first_year, last_year + 1):
        try:
            centre = event_day.replace(year=y)
        except ValueError:  # 29 Feb
            centre = event_day.replace(year=y, day=28)
        days = [centre + timedelta(days=k) for k in range(-window_days, window_days + 1)]
        vals = [hist.get(d.isoformat(), 0.0) for d in days]
        hits += sum(v >= threshold_mm for v in vals)
        total += len(vals)
        per_year.append({"year": y, "rain_mm": round(hist.get(centre.isoformat(), 0.0), 1),
                         "rainy_days": sum(v >= threshold_mm for v in vals)})
    return {"base_rate": hits / total if total else 0.0, "per_year": per_year,
            "years": f"{first_year}-{last_year}"}


# --------------------------------------------------------------------------- forecast
@lru_cache(maxsize=64)
def _ensemble_raw(lat: float, lon: float, hour_key: str) -> dict:
    """GFS 31-member ensemble; cached per location per hour (hour_key)."""
    return _get(ENSEMBLE, latitude=lat, longitude=lon, hourly="precipitation",
                models="gfs025", forecast_days=16)


def ensemble_probability(lat: float, lon: float, start: datetime, end: datetime,
                         threshold_mm: float) -> dict | None:
    """Fraction of ensemble members whose rain in the event window >= threshold.

    Returns None when the event is beyond the forecast horizon (~15 days).
    """
    lead_days = (start.date() - date.today()).days
    if lead_days > 14 or end < datetime.now():
        return None
    try:
        d = _ensemble_raw(round(lat, 2), round(lon, 2), datetime.now().strftime("%Y%m%d%H"))
    except httpx.HTTPError:
        return None
    times = d["hourly"]["time"]
    idx = [i for i, t in enumerate(times)
           if start <= datetime.fromisoformat(t) < end]
    if not idx:
        return None
    members = [k for k in d["hourly"] if k.startswith("precipitation")]
    sums = [sum((d["hourly"][m][i] or 0.0) for i in idx) for m in members]
    hits = sum(s >= threshold_mm for s in sums)
    return {"probability": hits / len(sums), "members": len(sums),
            "median_mm": round(sorted(sums)[len(sums) // 2], 1), "lead_days": lead_days}


# --------------------------------------------------------------------------- observed
def _series(url: str, lat: float, lon: float, day0: str, day1: str, model: str) -> dict[str, float]:
    d = _get(url, latitude=lat, longitude=lon, start_date=day0, end_date=day1,
             hourly="precipitation", models=model)
    return {t: (p or 0.0) for t, p in zip(d["hourly"]["time"], d["hourly"]["precipitation"])}


def _source_plan(end: datetime) -> dict[str, tuple[str, str]]:
    """Which API and model each of the two witnesses uses for this window."""
    if (date.today() - end.date()).days < 6:  # ERA5 lags ~5 days: use the live analysis
        return {"ECMWF IFS (live)": (FORECAST, "ecmwf_ifs025"), "NOAA GFS (live)": (FORECAST, "gfs_seamless")}
    return {"ECMWF ERA5": (ARCHIVE, "era5"), "NOAA GFS": (HIST_FORECAST, "gfs_seamless")}


def source_links(lat: float, lon: float, start: datetime, end: datetime) -> dict[str, str]:
    """Exact public URLs anyone can open to re-check the rainfall we used."""
    day0, day1 = start.date().isoformat(), end.date().isoformat()
    return {name: str(httpx.URL(url, params={"latitude": lat, "longitude": lon, "start_date": day0,
                                             "end_date": day1, "hourly": "precipitation", "models": model,
                                             "timezone": TZ}))
            for name, (url, model) in _source_plan(end).items()}


def observed_hourly(lat: float, lon: float, start: datetime, end: datetime) -> dict[str, list[dict]]:
    """Hourly rain in [start, end) from two independent sources ("two witnesses").

    Source A: ECMWF ERA5 reanalysis (lags ~5 days, so recent events use the
              ECMWF IFS model analysis instead).
    Source B: NOAA GFS, from the historical-forecast archive - a different
              agency and model, so the two are genuinely independent.
    """
    day0, day1 = start.date().isoformat(), end.date().isoformat()
    out: dict[str, list[dict]] = {}
    for name, (url, model) in _source_plan(end).items():
        try:
            series = _series(url, lat, lon, day0, day1, model)
        except httpx.HTTPError:
            continue
        out[name] = [{"time": t, "rain_mm": round(v, 2)} for t, v in sorted(series.items())
                     if start <= datetime.fromisoformat(t) < end]
    return out
