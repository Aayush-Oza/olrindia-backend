import requests

MYMEMORY_URL = "https://api.mymemory.translated.net/get"

# Every field that must NEVER be translated
SKIP_KEYS = {
    # Auth & tokens
    'email', 'password', 'confirm_password', 'new_password',
    'token', 'id_token', 'google_id', 'fcm_token',

    # Payments
    'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature',
    'plan', 'amount_inr', 'duration_days',

    # Location codes (not text, no translation needed)
    'pincode', 'latitude', 'longitude',

    # Contact
    'mobile', 'phone', 'gst_number',

    # Media / files
    'image', 'image1', 'image2', 'image3', 'image4', 'image5',
    'photo', 'url', 'profile_photo', 'share_slug',

    # Product structure
    'category', 'subcategory',
    'rent_per_hour', 'rent_per_km', 'rent_per_day', 'rent_per_month',
    'security_deposit', 'click_count', 'is_active', 'status',
    'deactivated_by', 'edit_deadline', 'product_id', 'vendor_id', 'user_id',

    # Vendor plan/subscription
    'subscription_plan', 'pending_plan',

    # Admin / system
    'role', 'strike_count', 'strike_number', 'suspended_reason',
    'conv_id', 'sender_role',
}


def translate_to_english(text):
    if not text or not isinstance(text, str) or not text.strip():
        return text

    # Already ASCII/English - skip API call entirely
    try:
        text.encode('ascii')
        return text
    except UnicodeEncodeError:
        pass

    try:
        resp = requests.get(MYMEMORY_URL, params={
            "q": text.strip(),
            "langpair": "autodetect|en",
            "de": "olrindia2026@gmail.com"
        }, timeout=5)

        if resp.status_code == 200:
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and "PLEASE SELECT" not in translated.upper():
                return translated.strip()
    except Exception:
        pass

    return text  # Always fallback to original, never block


def translate_all_strings(obj, _key=None):
    if isinstance(obj, dict):
        return {
            k: (translate_all_strings(v, _key=k) if k not in SKIP_KEYS else v)
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [translate_all_strings(i, _key=_key) for i in obj]
    elif isinstance(obj, str):
        v = obj.strip()
        if not v:
            return obj
        # Skip URLs, emails, pure numbers, tokens (extra safety net)
        if (v.startswith('http') or
            '@' in v or
            v.isdigit() or
            len(v) < 3):  # single chars / 2-char codes not worth translating
            return obj
        return translate_to_english(v)
    return obj