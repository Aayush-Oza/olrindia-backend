# OLR India - Razorpay Utility
# Handles order creation and payment signature verification

import hmac
import hashlib
import razorpay
from flask import current_app


def get_razorpay_client():
    """Returns an authenticated Razorpay client using keys from config."""
    return razorpay.Client(
        auth=(
            current_app.config["RAZORPAY_KEY_ID"],
            current_app.config["RAZORPAY_KEY_SECRET"],
        )
    )


def create_order(amount_inr: float, plan: str, vendor_id: int) -> dict | None:
    """
    Create a Razorpay order for a subscription plan.

    amount_inr  : Price in INR (e.g. 249, 599, 999)
    plan        : "starter" | "growth" | "premium"
    vendor_id   : Vendor's DB id (stored as receipt for tracing)

    Returns Razorpay order dict on success, None on failure.
    """
    try:
        client = get_razorpay_client()
        order = client.order.create({
            "amount":   int(amount_inr * 100),   # Razorpay uses paise
            "currency": "INR",
            "receipt":  f"vendor_{vendor_id}_plan_{plan}",
            "notes": {
                "vendor_id": str(vendor_id),
                "plan":      plan,
            }
        })
        return order
    except Exception as e:
        current_app.logger.error(f"Razorpay create_order failed: {e}")
        return None


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """
    Verify Razorpay payment signature to confirm payment is genuine.

    Razorpay signs: HMAC-SHA256(order_id + "|" + payment_id, key_secret)
    We recompute and compare - if they match, payment is authentic.
    """
    try:
        secret = current_app.config["RAZORPAY_KEY_SECRET"].encode("utf-8")
        msg    = f"{order_id}|{payment_id}".encode("utf-8")
        expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        current_app.logger.error(f"Razorpay verify_signature failed: {e}")
        return False
    
def fetch_payment(payment_id):
    try:
        client = get_razorpay_client()
        return client.payment.fetch(payment_id)
    except Exception as e:
        current_app.logger.error(f"Razorpay fetch_payment failed: {e}")
        return None