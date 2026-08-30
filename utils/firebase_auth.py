import os
import firebase_admin
from firebase_admin import credentials, auth as fb_auth

from dotenv import load_dotenv

load_dotenv()

#SERVICE_ACCOUNT_PATH = os.getenv(
#    "FIREBASE_SERVICE_ACCOUNT_PATH",
#    "firebase-service-account.json"
#)
SERVICE_ACCOUNT_PATH = r"D:\OLRINDIA\site\backend\firebase-service-account.json"
def _init_firebase():
    if firebase_admin._apps:
        return
    print(f"[Firebase] Using: {SERVICE_ACCOUNT_PATH}")
    print(f"[Firebase] Exists: {os.path.exists(SERVICE_ACCOUNT_PATH)}")
    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)

_init_firebase()

def verify_google_token(id_token: str) -> dict | None:
    if not id_token:
        return None
    try:
        decoded = fb_auth.verify_id_token(id_token.strip(), clock_skew_seconds=60)
        if not decoded.get("email_verified", False):
            return None
        email = (decoded.get("email") or "").strip().lower()
        if not email:
            return None
        return {
            "uid":     decoded.get("uid", ""),
            "email":   email,
            "name":    decoded.get("name") or email.split("@")[0].replace(".", " ").title(),
            "picture": decoded.get("picture") or None,
        }
    except fb_auth.ExpiredIdTokenError:
        print("[Firebase] Token expired.")
        return None
    except fb_auth.InvalidIdTokenError:
        print("[Firebase] Invalid token.")
        return None
    except Exception as e:
        print(f"[Firebase] Error: {e}")
        return None

from firebase_admin import firestore as fb_firestore

def sync_identity_to_conversations(role, entity_id, name, photo_url):
    """
    Updates this user's/vendor's name+photo on every chat conversation
    they're part of. Runs server-side via Firebase Admin - no dependency
    on the browser's own Firebase sign-in, so this always succeeds if
    Firestore is reachable.
    """
    try:
        db_fs = fb_firestore.client()
        field = 'user_uid' if role == 'user' else 'vendor_uid'
        uid = f"{role}_{entity_id}"
        name_field = 'user_name' if role == 'user' else 'vendor_name'
        photo_field = 'user_photo' if role == 'user' else 'vendor_photo'

        convos = db_fs.collection('conversations').where(field, '==', uid).stream()
        for doc in convos:
            doc.reference.update({
                name_field: name or '',
                photo_field: photo_url or None
            })
    except Exception as e:
        print(f"[Firestore sync] Failed to sync identity: {e}")