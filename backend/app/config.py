import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
PAYPAL_BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")

INR_PER_USD = float(os.getenv("INR_PER_USD", "88"))
MARGIN = float(os.getenv("PRICING_MARGIN", "0.25"))
PLATFORM_FEE_INR = float(os.getenv("PLATFORM_FEE_INR", "99"))
CUTOFF_HOURS = float(os.getenv("CUTOFF_HOURS", "24"))
AREA_DAY_LIMIT_INR = float(os.getenv("AREA_DAY_LIMIT_INR", "500000"))

DEMO_REPLAY_DATE = os.getenv("DEMO_REPLAY_DATE", "2023-11-15")   # rainy evening: pays out
DEMO_DRY_DATE = os.getenv("DEMO_DRY_DATE", "2023-11-26")         # light drizzle: no payout
DEMO_REPLAY_SECONDS = float(os.getenv("DEMO_REPLAY_SECONDS", "60"))

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).resolve().parents[1] / "eventrain.db"))
