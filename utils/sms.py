# utils/sms.py
# MSG91 SMS utility — sends verification magic link via SMS
# Best-effort: silently skips if MSG91 keys not configured (DLT pending)

import os
import requests

def send_verification_sms(mobile: str, name: str, token: str, role: str, frontend_url: str) -> bool:
    """
    Sends verification magic link SMS via MSG91.
    Returns True if sent, False if skipped or failed. Never raises.
    """
    api_key     = os.getenv("MSG91_API_KEY", "")
    template_id = os.getenv("MSG91_TEMPLATE_ID", "")

    if not api_key or not template_id or not mobile:
        return False  # DLT not ready yet — skip silently

    verify_link = f"{frontend_url}/{role}/verify-email.html?token={token}"

    try:
        payload = {
            "template_id": template_id,
            "short_url":   "0",
            "recipients": [
                {
                    "mobiles":     f"91{mobile}",
                    "name":        name,
                    "verify_link": verify_link,
                }
            ]
        }
        headers = {
            "accept":       "application/json",
            "content-type": "application/json",
            "authkey":      api_key,
        }
        resp = requests.post(
            "https://api.msg91.com/api/v5/flow/",
            json=payload,
            headers=headers,
            timeout=8
        )
        return resp.json().get("type") == "success"

    except Exception as e:
        print(f"[SMS] Failed: {e}")
        return False