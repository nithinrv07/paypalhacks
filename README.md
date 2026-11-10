# EventRain Cover

Rain protection for small events, priced per event by AI, paid through PayPal, with zero claim forms.

```
frontend/  Next.js 16 + Tailwind + Leaflet + Recharts + PayPal JS SDK   (port 3000)
backend/   FastAPI + scikit-learn + SQLite + PayPal REST                 (port 8000)
```

## Run it

Backend (first terminal):

```bash
cd backend
pip install -r requirements.txt
python -m ml.train          # one-time, ~2 min: downloads 15 yrs of Chennai rain, trains the model
uvicorn app.main:app --port 8000
```

Frontend (second terminal):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The frontend forwards `/api/*` to the backend.

> Next.js dev needs about 2 GB of free memory. If it crashes with "memory allocation failed", close other apps first.

## PayPal

Without keys, PayPal runs in **mock mode**, so the whole flow still works. To use the real Sandbox:

1. Create a Sandbox app at https://developer.paypal.com/dashboard/applications/sandbox
2. `cp backend/.env.example backend/.env` and fill in `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`
3. Restart the backend. The quote → checkout page now shows real PayPal buttons.
4. Pay with your Sandbox **personal** account, and use that same email as the payout email, so you can see the payout land.

| What | PayPal API |
|---|---|
| Collect premium | Orders v2: create + capture |
| Confirm payment | Webhook `PAYMENT.CAPTURE.COMPLETED` → `/api/webhooks/paypal` |
| Send payout | Payouts API (`/v1/payments/payouts`) |
| Track payout | Payouts status + `PAYMENT.PAYOUTS-ITEM.*` webhooks |

Sandbox charges in USD; the app shows ₹ (`INR_PER_USD=88`).

## How the AI works

**Pricing** (`backend/ml/train.py`, `backend/app/pricing.py`)
- The training data is 15 years (2010–2024) of hourly ECMWF ERA5 rain at 4 Chennai points, turned into 789k labelled event windows ("did rain in this window reach X mm?").
- Features: season, start hour, duration, threshold, and local climatology at the venue (computed leave-one-year-out).
- On held-out years 2023–24, **logistic regression** (Brier 0.0146, AUC 0.85) beat gradient boosting (0.0155) and climatology alone (0.0278). It was chosen and is well calibrated.
- Within 14 days of the event, it blends in a **live 31-member GFS ensemble forecast** (the share of runs where the window reaches the threshold), weighted more heavily as the date gets closer.
- `Premium = P × payout × 1.25 + ₹99`

**Trigger** (`backend/app/trigger.py`)
- Two independent sources measure rain at the venue: **ECMWF ERA5** and **NOAA GFS**.
- If both agree, it pays (or closes) automatically. If they differ only slightly, it decides on the average. If they disagree strongly, the policy is **flagged** for human review in Admin.
- Every reading and decision is stored, so each payout can be explained.

**Fraud rules:** cover must be bought 24 h before the event, total cover is capped per area per day, and the forecast raises the price when rain is already likely.

## Demo (3 minutes)

1. Landing → **Try the live demo** → tick Demo mode → **Fill demo story** (Besant Nagar, 4–10 PM, ₹20,000, 10 mm) → enter a payout email → Continue.
2. Pay with PayPal (Sandbox or mock). The policy is ACTIVE and the certificate is ready.
3. **▶ Start the event.** It replays the real rainfall of **15 Nov 2023** at Besant Nagar in 60 s, and the gauge crosses 10 mm.
4. The trigger checker reads both sources (ERA5 24.9 mm, GFS 11.0 mm), both above 10 mm, so the **payout is sent automatically** with a plain-language summary.
5. Admin shows money in vs out, model calibration, and lets you resolve flagged cases. (Pick the 20 mm threshold to see a flagged case: GFS says only 11 mm.)

Tune with `DEMO_REPLAY_DATE` and `DEMO_REPLAY_SECONDS` in `backend/.env`.

## Not done yet
- Refunds API for cancellations before the cut-off
- An LLM-written summary (the current one is a template)
- Real deployment (Vercel + Render) and webhook registration (needs a public URL)

Hackathon prototype. Selling insurance in India needs IRDAI approval, so a real launch would partner with a licensed insurer.
