# OLR India - Auth Middleware
# Protects routes by verifying JWT tokens
# Checks role-based access (user / vendor / admin)
# Import and use as decorators on protected routes

from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity


def user_required(fn):
    """
    Protect route - only verified users can access.

    Usage:
        @app.route("/user/dashboard")
        @user_required
        def dashboard():
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            # Verify JWT token from HttpOnly cookie
            verify_jwt_in_request()

            # Get JWT payload
            claims = get_jwt()

            # Check role
            if claims.get("role") != "user":
                return jsonify({
                    "success": False,
                    "message": "Access denied. User account required."
                }), 403

            return fn(*args, **kwargs)

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Unauthorized. Please login.",
                "error": str(e)
            }), 401

    return wrapper


def vendor_required(fn):
    """
    Protect route - only verified vendors can access.

    Usage:
        @app.route("/vendor/listings")
        @vendor_required
        def listings():
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
            claims = get_jwt()

            if claims.get("role") != "vendor":
                return jsonify({
                    "success": False,
                    "message": "Access denied. Vendor account required."
                }), 403

            return fn(*args, **kwargs)

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Unauthorized. Please login.",
                "error": str(e)
            }), 401

    return wrapper


def admin_required(fn):
    """
    Protect route - only admin can access.

    Usage:
        @app.route("/admin/dashboard")
        @admin_required
        def admin_dashboard():
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
            claims = get_jwt()

            if claims.get("role") != "admin":
                return jsonify({
                    "success": False,
                    "message": "Access denied. Admin account required."
                }), 403

            return fn(*args, **kwargs)

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Unauthorized. Please login.",
                "error": str(e)
            }), 401

    return wrapper


def any_role_required(fn):
    """
    Protect route - any logged in user (user/vendor/admin) can access.
    Used for shared routes like profile update.

    Usage:
        @app.route("/profile")
        @any_role_required
        def profile():
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
            claims = get_jwt()

            role = claims.get("role")
            if role not in ["user", "vendor", "admin"]:
                return jsonify({
                    "success": False,
                    "message": "Access denied. Please login."
                }), 403

            return fn(*args, **kwargs)

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Unauthorized. Please login.",
                "error": str(e)
            }), 401

    return wrapper


def get_current_user_id() -> int:
    """
    Helper - get current logged in user/vendor/admin ID from JWT.
    Call this inside any protected route.

    Usage:
        from middleware.auth_middleware import get_current_user_id
        user_id = get_current_user_id()
    """
    claims = get_jwt()
    return int(get_jwt_identity())


def get_current_role() -> str:
    """
    Helper - get current logged in user role from JWT.

    Usage:
        from middleware.auth_middleware import get_current_role
        role = get_current_role()  # "user" / "vendor" / "admin"
    """
    claims = get_jwt()
    return claims.get("role")