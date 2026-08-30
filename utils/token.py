from flask import request
from datetime import timedelta
from flask_jwt_extended import create_access_token, create_refresh_token


def _is_mobile() -> bool:
    """Detect if request is coming from mobile app (Flutter/okhttp)."""
    user_agent = request.headers.get('User-Agent', '').lower()
    return 'okhttp' in user_agent or 'dart' in user_agent


def _token_expiry() -> timedelta:
    """1 year for mobile app, 7 days for web."""
    return timedelta(days=365) if _is_mobile() else timedelta(days=7)


def generate_tokens(identity: dict) -> dict:
    """
    Generate both access and refresh tokens for a user/vendor/admin.

    identity = {
        "id": 1,
        "role": "user"   # or "vendor" or "admin"
    }

    Returns:
        {
            "access_token": "...",
            "refresh_token": "..."
        }
    """
    expires = _token_expiry()

    access_token = create_access_token(
        identity=str(identity["id"]),
        additional_claims={"role": identity["role"]},
        expires_delta=expires,
    )

    refresh_token = create_refresh_token(
        identity=str(identity["id"]),
        additional_claims={"role": identity["role"]},
        expires_delta=expires,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


def generate_access_token(identity) -> str:
    """
    Generate only access token.
    Used in refresh token endpoint - when access token expires,
    refresh token is used to get a new access token only.

    identity = str(id) passed directly from get_jwt_identity()
    """
    expires = _token_expiry()
    return create_access_token(
        identity=identity,
        expires_delta=expires,
    )