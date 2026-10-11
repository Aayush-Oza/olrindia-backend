# backend/utils/fcm.py
import requests
from google.oauth2 import service_account
import google.auth.transport.requests

_SERVICE_ACCOUNT_FILE = 'firebase-service-account.json'
_SCOPES = ['https://www.googleapis.com/auth/firebase.messaging']
_PROJECT_ID = 'olrindia-42b50'

def _get_access_token():
    creds = service_account.Credentials.from_service_account_file(
        _SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token

def send_chat_notification(fcm_token: str, sender_name: str, text: str, conv_id: str):
    """Send a chat push notification via FCM v1 API."""
    if not fcm_token:
        return
    try:
        access_token = _get_access_token()
        url = f'https://fcm.googleapis.com/v1/projects/{_PROJECT_ID}/messages:send'
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
                },
                'android': {'priority': 'high'},
                'apns': {'headers': {'apns-priority': '10'}},
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