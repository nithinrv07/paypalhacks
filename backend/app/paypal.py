"""PayPal REST client: Orders v2 (premium in), Payouts (money out), Webhooks.

If PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET are not set, it runs in MOCK mode so
the whole flow still works offline. Add Sandbox keys to backend/.env to go live
against https://api-m.sandbox.paypal.com.
"""
from __future__ import annotations

import time
import uuid

import httpx

from . import config


class PayPal:
    def __init__(self):
        self._token: str | None = None
        self._token_exp = 0.0
        self.http = httpx.Client(base_url=config.PAYPAL_BASE, timeout=30)

    @property
    def mock(self) -> bool:
        return not (config.PAYPAL_CLIENT_ID and config.PAYPAL_CLIENT_SECRET)

    # ------------------------------------------------------------------ auth
    def _auth(self) -> dict:
        if not self._token or time.time() > self._token_exp - 60:
            r = self.http.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
                               auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_CLIENT_SECRET))
            r.raise_for_status()
            d = r.json()
            self._token, self._token_exp = d["access_token"], time.time() + d["expires_in"]
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------ premium in
    def create_order(self, amount_usd: float, policy_id: int, description: str) -> dict:
        if self.mock:
            return {"id": f"MOCK-ORDER-{uuid.uuid4().hex[:10].upper()}", "status": "CREATED"}
        body = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": f"policy-{policy_id}",
                "custom_id": str(policy_id),
                "description": description[:127],
                "amount": {"currency_code": "USD", "value": f"{amount_usd:.2f}"},
            }],
            "payment_source": {"paypal": {"experience_context": {
                "brand_name": "EventRain Cover", "user_action": "PAY_NOW",
                "shipping_preference": "NO_SHIPPING"}}},
        }
        r = self.http.post("/v2/checkout/orders", json=body,
                           headers={**self._auth(), "PayPal-Request-Id": f"order-{policy_id}-{uuid.uuid4().hex[:8]}"})
        r.raise_for_status()
        return r.json()

    def capture_order(self, order_id: str) -> dict:
        """Returns {'status': 'COMPLETED', 'capture_id': ..., 'raw': ...}."""
        if self.mock:
            return {"status": "COMPLETED", "capture_id": f"MOCK-CAP-{uuid.uuid4().hex[:10].upper()}", "raw": {}}
        r = self.http.post(f"/v2/checkout/orders/{order_id}/capture", headers=self._auth())
        r.raise_for_status()
        d = r.json()
        cap = d["purchase_units"][0]["payments"]["captures"][0]
        return {"status": cap["status"], "capture_id": cap["id"], "raw": d}

    # ------------------------------------------------------------------ money out
    def send_payout(self, email: str, amount_usd: float, policy_id: int, note: str) -> dict:
        """Returns {'batch_id', 'status'} - status PENDING/PROCESSING/SUCCESS."""
        if self.mock:
            return {"batch_id": f"MOCK-PAYOUT-{uuid.uuid4().hex[:10].upper()}", "status": "SUCCESS", "raw": {}}
        body = {
            "sender_batch_header": {
                "sender_batch_id": f"eventrain-{policy_id}-{uuid.uuid4().hex[:8]}",
                "email_subject": "EventRain Cover: your rain payout has arrived",
                "email_message": note[:1000],
            },
            "items": [{
                "recipient_type": "EMAIL", "receiver": email, "note": note[:4000],
                "sender_item_id": f"policy-{policy_id}",
                "amount": {"value": f"{amount_usd:.2f}", "currency": "USD"},
            }],
        }
        r = self.http.post("/v1/payments/payouts", json=body, headers=self._auth())
        r.raise_for_status()
        d = r.json()
        return {"batch_id": d["batch_header"]["payout_batch_id"],
                "status": d["batch_header"]["batch_status"], "raw": d}

    def payout_status(self, batch_id: str) -> str:
        if self.mock:
            return "SUCCESS"
        r = self.http.get(f"/v1/payments/payouts/{batch_id}", headers=self._auth())
        r.raise_for_status()
        return r.json()["batch_header"]["batch_status"]

    # ------------------------------------------------------------------ webhooks
    def verify_webhook(self, headers: dict, event: dict) -> bool:
        if self.mock or not config.PAYPAL_WEBHOOK_ID:
            return self.mock  # never trust unverified webhooks against a real account
        body = {
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "webhook_id": config.PAYPAL_WEBHOOK_ID,
            "webhook_event": event,
        }
        r = self.http.post("/v1/notifications/verify-webhook-signature", json=body, headers=self._auth())
        return r.is_success and r.json().get("verification_status") == "SUCCESS"


paypal = PayPal()
