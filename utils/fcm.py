import time
import requests
from google.oauth2 import service_account
import google.auth.transport.requests

_SERVICE_ACCOUNT_FILE = 'firebase-service-account.json'
_SCOPES = ['https://www.googleapis.com/auth/firebase.messaging']
_PROJECT_ID = 'olrindia-42b50'
_notify_cache = {}

def _get_access_token():
    creds = service_account.Credentials.from_service_account_file(
        _SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token

def send_chat_notification(fcm_token: str, sender_name: str, text: str, conv_id: str, sender_photo: str = None):
    # Dedup — same conv+text within 3 seconds = skip (prevents web+app double notify)
    cache_key = f"{conv_id}:{text[:30]}"
    now = time.time()
    if _notify_cache.get(cache_key, 0) > now - 3:
        return
    _notify_cache[cache_key] = now

    if not fcm_token:
        return
    try:
        access_token = _get_access_token()
        url = f'https://fcm.googleapis.com/v1/projects/{_PROJECT_ID}/messages:send'
        
        android_notif = {
            'tag': conv_id,         
            'channel_id': 'olr_chat',
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
        }

        payload = {
            'message': {
                'token': fcm_token,
                'notification': {
                    'title': sender_name,
                    'body': text[:100],
                },
                'data': {
                    'type': 'chat',
                    'conv_id': conv_id,
                    'sender_photo': sender_photo or '',

                },
                'android': {
                    'priority': 'high',
                    'notification': android_notif,
                },
                'apns': {
                    'headers': {'apns-priority': '10'},
                    'payload': {
                        'aps': {'thread-id': conv_id}  # groups iOS notifications by conv
                    }
                },
            }
        }
        requests.post(
            url, json=payload,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            timeout=8
        )
    except Exception as e:
        print(f'[FCM] send_chat_notification failed: {e}')