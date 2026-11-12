"""Payout styles.

fixed      - all of the cover at the chosen threshold (the original product)
graduated  - 25% at 5 mm, 50% at 10 mm, 100% at 20 mm: a light shower still
             helps, a downpour pays in full. Uses the three thresholds the risk
             model was trained on, so every level is priced from real data.
"""
from __future__ import annotations

GRADUATED: list[tuple[float, float]] = [(5.0, 0.25), (10.0, 0.5), (20.0, 1.0)]


def ladder(mode: str | None, threshold_mm: float) -> list[tuple[float, float]]:
    """[(rain_mm, fraction_of_cover), ...] sorted by rain."""
    return GRADUATED if mode == "graduated" else [(float(threshold_mm), 1.0)]


def fraction(rain_mm: float, steps: list[tuple[float, float]]) -> float:
    """Share of the cover earned by this much rain."""
    return max((f for mm, f in steps if rain_mm >= mm), default=0.0)


def describe(mode: str | None, threshold_mm: float, cover: float, inr) -> str:
    if mode == "graduated":
        return ", ".join(f"{inr(cover * f)} at {mm:g} mm" for mm, f in GRADUATED)
    return f"{inr(cover)} at {threshold_mm:g} mm"
