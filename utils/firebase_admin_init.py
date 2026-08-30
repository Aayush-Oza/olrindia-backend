# ── Firebase Admin SDK init (shared across app) ──────────────────────────────
import os
import firebase_admin
from firebase_admin import credentials

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVICE_ACCOUNT_PATH = os.path.join(_BASE_DIR, "firebase-service-account.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(_SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)