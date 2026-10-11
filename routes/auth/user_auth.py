# OLR India - User Auth Routes
# Handles all authentication for users (customers)
# POST /auth/user/register
# GET  /auth/user/verify-email?token=xxx
# POST /auth/user/login
# POST /auth/user/refresh
# POST /auth/user/logout
# POST /auth/user/forgot-password
# POST /auth/user/reset-password

from itertools import product
import re
import bcrypt
from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity, unset_jwt_cookies
from extensions import limiter

from extensions import db
from models.user import User, UserVerificationToken, UserPasswordResetToken
from models.vendor import Product  # or wherever Product is defined
from utils.email import send_verification_email, send_password_reset_email
from utils.fcm import send_chat_notification
from utils.token import generate_tokens, generate_access_token,_is_mobile
from models.vendor import Vendor
from utils.firebase_auth import verify_google_token
from utils.s3 import compress_and_upload, delete_from_s3
from firebase_admin import auth as fb_auth
import utils.firebase_auth  # triggers Firebase Admin init (already does _init_firebase() on import)
from flask import Blueprint, request, jsonify, make_response, current_app   # ← added current_app
from utils.firebase_auth import verify_google_token, sync_identity_to_conversations
from models.user import Wishlist

user_auth_bp = Blueprint("user_auth", __name__)


def validate_password(password, confirm_password):
    """
    Validate password strength and confirmation.
    Rules: 8+ chars, 1 uppercase, 1 lowercase, 1 number, 1 special char
    """
    if password != confirm_password:
        return False, "Passwords do not match."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number."
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character."
    return True, None


# ── REGISTER ──────────────────────────────────────────────────────────────────
@user_auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per hour")
def register():
    """
    Register a new user account.

    Request body:
    {
        "name": "John Doe",
        "email": "john@example.com",
        "password": "Password@123",
        "confirm_password": "Password@123",
        "mobile": "9876543210",        # Optional
        "pincode": "400068",           # Optional - auto fills location
        "state": "Maharashtra",        # Auto filled from pincode API on frontend
        "city": "Mumbai",              # Auto filled from pincode API on frontend
        "area": "Dahisar",             # Auto filled from pincode API on frontend
        "latitude": 19.2333,           # Optional - from browser geolocation
        "longitude": 72.8500           # Optional - from browser geolocation
    }

    Location flow (frontend):
    1. User enters pincode
    2. Frontend calls: https://api.postalpincode.in/pincode/400068 (FREE)
    3. Auto fills state, city, area
    4. Browser geolocation fills lat/long (optional)
    """
    try:
        data = request.get_json()

        # ── Validate required fields ──────────────────────────────────────────
        required = ["name", "email", "password", "confirm_password"]
        for field in required:
            if not data.get(field):
                return jsonify({
                    "success": False,
                    "message": f"{field} is required."
                }), 400

        # ── Validate password strength ────────────────────────────────────────
        is_valid, error = validate_password(data["password"], data["confirm_password"])
        if not is_valid:
            return jsonify({"success": False, "message": error}), 400

        name = data["name"].strip()
        email = data["email"].strip().lower()
        mobile = data.get("mobile", "").strip() or None
        pincode = data.get("pincode", "").strip() or None
        state = data.get("state", "").strip() or None
        city = data.get("city", "").strip() or None
        area = data.get("area", "").strip() or None
        latitude = data.get("latitude") or None
        longitude = data.get("longitude") or None

        # ── Check duplicates ──────────────────────────────────────────────────
        if User.query.filter_by(email=email).first():
            return jsonify({
                "success": False,
                "message": "An account with this email already exists."
            }), 409

        if mobile and User.query.filter_by(mobile=mobile).first():
            return jsonify({
                "success": False,
                "message": "An account with this mobile number already exists."
            }), 409

        # ── Hash password ─────────────────────────────────────────────────────
        password_hash = bcrypt.hashpw(
            data["password"].encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # ── Create user ───────────────────────────────────────────────────────
        user = User(
            name=name,
            email=email,
            mobile=mobile,
            password_hash=password_hash,
            pincode=pincode,
            state=state,
            city=city,
            area=area,
            latitude=latitude,
            longitude=longitude,
            is_verified=False
        )
        db.session.add(user)
        db.session.flush()

        # ── Generate verification token ───────────────────────────────────────
        token_obj = UserVerificationToken.generate(user.id)
        db.session.add(token_obj)
        db.session.commit()

        # ── Send magic link email ─────────────────────────────────────────────
        email_sent = send_verification_email(
            to_email=email,
            name=name,
            token=token_obj.token,
            role="user"
        )

        if not email_sent:
            return jsonify({
                "success": True,
                "message": "Account created but email failed. Please use resend verification."
            }), 201

        return jsonify({
            "success": True,
            "message": "Account created! Please check your email to verify your account."
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": "Registration failed. Please try again.",
            "error": str(e)
        }), 500


# ── VERIFY EMAIL ──────────────────────────────────────────────────────────────
@user_auth_bp.route("/verify-email", methods=["GET"])
@limiter.limit("10 per hour")
def verify_email():
    """Verify user email via magic link token"""
    try:
        token = request.args.get("token")
        if not token:
            return jsonify({"success": False, "message": "Verification token is missing."}), 400

        token_obj = UserVerificationToken.query.filter_by(token=token).first()
        if not token_obj:
            return jsonify({"success": False, "message": "Invalid verification link."}), 400

        if not token_obj.is_valid():
            return jsonify({
                "success": False,
                "message": "Link expired or already used. Please request a new one."
            }), 400

        user = User.query.get(token_obj.user_id)
        user.is_verified = True
        token_obj.is_used = True
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Email verified successfully! You can now login."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Verification failed.", "error": str(e)}), 500


# ── LOGIN ─────────────────────────────────────────────────────────────────────
@user_auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute;50 per hour")
def login():
    """
    Login user with email and password.
    Returns JWT access + refresh tokens in HttpOnly cookies.
    """
    try:
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"success": False, "message": "Email and password are required."}), 400
        
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"success": False, "message": "Invalid email or password."}), 401

        if not user.is_active:
            return jsonify({"success": False, "message": "Account deactivated. Contact support."}), 403

        if not user.is_verified:
            return jsonify({
                "success": False,
                "message": "Please verify your email first.",
                "resend_verification": True
            }), 403

        if not user.password_hash or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
            return jsonify({"success": False, "message": "Invalid email or password."}), 401

        identity = {"id": user.id, "role": "user"}
        tokens = generate_tokens(identity)
        cookie_max_age = 365*24*60*60 if _is_mobile() else 7*24*60*60

        response = make_response(jsonify({
            "success": True,
            "message": "Login successful.",
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": "user",
                "city": user.city,
                "state": user.state
            }
        }), 200)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/user/"
        response.set_cookie("access_token_cookie", tokens["access_token"],
                           httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,path=cookie_path)
        response.set_cookie("refresh_token_cookie", tokens["refresh_token"],
                           httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,path=cookie_path)

        return response

    except Exception as e:
        return jsonify({"success": False, "message": "Login failed.", "error": str(e)}), 500


# ── REFRESH TOKEN ─────────────────────────────────────────────────────────────
@user_auth_bp.route("/refresh", methods=["POST"])
@limiter.limit("30 per minute")
@jwt_required(refresh=True)
def refresh():
    """Get new access token using refresh token"""
    try:
        identity = get_jwt_identity()
        new_access_token = generate_access_token(identity)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/user/"
        response = make_response(jsonify({"success": True, "message": "Token refreshed."}), 200)
        response.set_cookie("access_token_cookie", new_access_token,
                           httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=15*60,path=cookie_path)
        return response

    except Exception as e:
        return jsonify({"success": False, "message": "Token refresh failed.", "error": str(e)}), 401


# ── LOGOUT ────────────────────────────────────────────────────────────────────
@user_auth_bp.route("/logout", methods=["POST"])
def logout():
    response = make_response(jsonify({"success": True, "message": "Logged out successfully."}), 200)
    cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/user/"
    response.delete_cookie("access_token_cookie", path=cookie_path)
    response.delete_cookie("refresh_token_cookie", path=cookie_path)
    return response


# ── FORGOT PASSWORD ───────────────────────────────────────────────────────────
@user_auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    """Send password reset link to user's email"""
    try:
        data = request.get_json()
        email = data.get("email", "").strip().lower()

        if not email:
            return jsonify({"success": False, "message": "Email is required."}), 400

        user = User.query.filter_by(email=email).first()

        # Always return success - don't reveal if email exists (prevents enumeration)
        if not user:
            return jsonify({
                "success": True,
                "message": "If an account exists with this email, a reset link has been sent."
            }), 200

        token_obj = UserPasswordResetToken.generate(user.id)
        db.session.add(token_obj)
        db.session.commit()

        send_password_reset_email(to_email=email, name=user.name, token=token_obj.token, role="user")

        return jsonify({
            "success": True,
            "message": "If an account exists with this email, a reset link has been sent."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Something went wrong.", "error": str(e)}), 500


# ── RESET PASSWORD ────────────────────────────────────────────────────────────
@user_auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("5 per hour")
def reset_password():
    """Reset user password using token from reset email"""
    try:
        data = request.get_json()
        token = data.get("token", "").strip()
        new_password = data.get("new_password", "")
        confirm_password = data.get("confirm_password", "")

        if not token or not new_password or not confirm_password:
            return jsonify({
                "success": False,
                "message": "Token, new password and confirm password are required."
            }), 400

        # Validate password strength
        is_valid, error = validate_password(new_password, confirm_password)
        if not is_valid:
            return jsonify({"success": False, "message": error}), 400

        token_obj = UserPasswordResetToken.query.filter_by(token=token).first()
        if not token_obj or not token_obj.is_valid():
            return jsonify({
                "success": False,
                "message": "Invalid or expired reset link. Please request a new one."
            }), 400

        user = User.query.get(token_obj.user_id)
        user.password_hash = bcrypt.hashpw(
            new_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        token_obj.is_used = True
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Password reset successfully. You can now login."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Password reset failed.", "error": str(e)}), 500


# ── GOOGLE SIGN-IN ────────────────────────────────────────────────────────────
@user_auth_bp.route("/google", methods=["POST"])
@limiter.limit("10 per minute;50 per hour")
def google_login():
    """
    Sign in or register a user via Google Sign-In (Firebase).

    Request body:
    {
        "id_token": "<Firebase ID token from frontend signInWithPopup()>"
    }

    Flow:
    - Verifies the Firebase ID token server-side
    - If email already exists in users table → logs them in (issues JWT cookies)
    - If email is new → creates account automatically, then logs them in
    - Returns the same shape as /login so the frontend handles both identically
    """
    try:
        data = request.get_json()
        id_token = (data or {}).get("id_token", "")

        # ── Verify token with Firebase ────────────────────────────────────────
        google_data = verify_google_token(id_token)
        if not google_data:
            return jsonify({
                "success": False,
                "message": "Google sign-in failed. Invalid or expired token - please try again."
            }), 401

        email   = google_data["email"]
        name    = google_data["name"]
        uid     = google_data["uid"]
        picture = google_data["picture"]

        # ── Find or create user ───────────────────────────────────────────────
        created = False
        user = User.query.filter_by(email=email).first()

        if user:
            # Existing user - update google_id if not already stored
            if not user.google_id:
                user.google_id = uid
                db.session.commit()

            # Block deactivated accounts
            if not user.is_active:
                return jsonify({
                    "success": False,
                    "message": "Account deactivated. Please contact support."
                }), 403
        else:
            # New user - create account (no password needed, no email verification step)
            user = User(
                name=name,
                email=email,
                password_hash=None,   # Google users have no password
                google_id=uid,
                is_verified=True,     # Google already verified their email
                is_active=True,
            )
            db.session.add(user)
            db.session.commit()
            created = True

        # ── Issue JWT cookies (same as normal login) ──────────────────────────
        identity = {"id": user.id, "role": "user"}
        tokens = generate_tokens(identity)
        cookie_max_age = 365*24*60*60 if _is_mobile() else 7*24*60*60
        response = make_response(jsonify({
            "success": True,
                "message": "Account created successfully." if created else "Signed in successfully.",
                "is_new_user": created,
            "user": {
                "id":       user.id,
                "name":     user.name,
                "email":    user.email,
                "city":     user.city,
                "state":    user.state,
                "role":     "user",
            }
        }), 200)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/user/"
        response.set_cookie("access_token_cookie",  tokens["access_token"],
                            httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,path=cookie_path)
        response.set_cookie("refresh_token_cookie", tokens["refresh_token"],
                            httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,path=cookie_path)
        return response

    except Exception as e:
        db.session.rollback()
        import traceback
        print(traceback.format_exc())
        return jsonify({"success": False, "message": "Google sign-in failed.", "error": str(e)}), 500
    
from flask_jwt_extended import jwt_required, get_jwt_identity

# ── GET PROFILE ───────────────────────────────────────────────
@user_auth_bp.route("/profile", methods=["GET"])
@limiter.limit("60 per minute")
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    return jsonify({"success": True, "user": {
        "id": user.id, "name": user.name, "email": user.email,
        "mobile": user.mobile, "pincode": user.pincode,
        "area": user.area, "city": user.city, "state": user.state,
        "profile_photo": user.profile_photo,
        "profile_complete": bool(user.mobile and (user.city or user.pincode))
    }}), 200

# ── UPDATE PROFILE ────────────────────────────────────────────
@user_auth_bp.route("/profile", methods=["PUT"])
@limiter.limit("20 per minute")
@jwt_required()
def update_profile():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
    data = request.get_json()
    # Only these fields are updatable - email/mobile locked
    if data.get("name"):    user.name    = data["name"].strip()
    if data.get("mobile"):
        existing = User.query.filter(
            User.mobile == data["mobile"].strip(),
            User.id != user.id
        ).first()

        if existing:
            return jsonify({
                "success": False,
                "message": "Mobile number already linked to another account."
            }), 409

        user.mobile = data["mobile"].strip()
    if data.get("area"):    user.area    = data["area"].strip()
    if data.get("city"):    user.city    = data["city"].strip()
    if data.get("state"):   user.state   = data["state"].strip()
    if data.get("pincode"): user.pincode = data["pincode"].strip()
    db.session.commit()
    sync_identity_to_conversations('user', user.id, user.name, user.profile_photo)
    return jsonify({"success": True, "message": "Profile updated.", "user": {
        "id": user.id, "name": user.name, "email": user.email,
        "mobile": user.mobile, "pincode": user.pincode,
        "area": user.area, "city": user.city, "state": user.state
    }}), 200

# ── PROFILE PHOTO ─────────────────────────────────────────────
@user_auth_bp.route("/profile/photo", methods=["PUT"])
@limiter.limit("10 per hour")
@jwt_required()
def update_user_profile_photo():
    """Multipart upload. Field name: 'photo'. Replaces existing S3 image if any."""
    user_id = int(get_jwt_identity())
    u = User.query.get(user_id)
    if not u:
        return jsonify({"success": False, "message": "User not found."}), 404

    f = request.files.get("photo")
    if not f:
        return jsonify({"success": False, "message": "No photo provided."}), 400

    old_url = u.profile_photo
    url = compress_and_upload(f, folder="user-profiles")
    if not url:
        return jsonify({"success": False, "message": "Photo upload failed."}), 500

    u.profile_photo = url
    db.session.commit()

    if old_url:
        delete_from_s3(old_url)
    sync_identity_to_conversations('user', u.id, u.name, u.profile_photo)
    return jsonify({"success": True, "message": "Profile photo updated.", "url": url}), 200


@user_auth_bp.route("/profile/photo", methods=["DELETE"])
@limiter.limit("10 per hour")
@jwt_required()
def delete_user_profile_photo():
    user_id = int(get_jwt_identity())
    u = User.query.get(user_id)
    if not u:
        return jsonify({"success": False, "message": "User not found."}), 404
    if u.profile_photo:
        delete_from_s3(u.profile_photo)
        u.profile_photo = None
        db.session.commit()
    sync_identity_to_conversations('user', u.id, u.name, None)
    return jsonify({"success": True, "message": "Profile photo removed."}), 200

@user_auth_bp.route("/wishlist/products", methods=["GET"])
@limiter.limit("60 per minute")
@jwt_required()
def get_wishlist_products():
    user_id = int(get_jwt_identity())
    items = Wishlist.query.filter_by(user_id=user_id).all()
    
    products = []
    for i in items:
        product = Product.query.get(i.product_id)
        if product is None or not product.is_active:
            db.session.delete(i)
            continue
        d = product.to_dict(include_vendor_badge=True)
        products.append(d)
    
    db.session.commit()
    return jsonify({"success": True, "products": products}), 200

# ── WISHLIST ──────────────────────────────────────────────────

@user_auth_bp.route("/wishlist", methods=["GET"])
@limiter.limit("60 per minute")
@jwt_required()
def get_wishlist():
    user_id = int(get_jwt_identity())
    items = Wishlist.query.filter_by(user_id=user_id).all()
    
    wishlist_data = []
    for i in items:
        product = Product.query.get(i.product_id)
        if product is None or not product.is_active:
            # Product deleted OR inactive - auto cleanup
            db.session.delete(i)
            continue
        wishlist_data.append({
            "id": i.id,
            "product_id": i.product_id,
            "share_slug": product.share_slug,
            "created_at": str(i.created_at)
        })
    
    db.session.commit()
    return jsonify({"success": True, "wishlist": wishlist_data}), 200

@user_auth_bp.route("/wishlist", methods=["POST"])
@limiter.limit("30 per minute")
@jwt_required()
def add_to_wishlist():
    user_id = int(get_jwt_identity())
    product_id = request.get_json().get("product_id")
    if not product_id:
        return jsonify({"success": False, "message": "product_id required."}), 400
    exists = Wishlist.query.filter_by(user_id=user_id, product_id=product_id).first()
    if exists:
        return jsonify({"success": False, "message": "Already in wishlist."}), 409
    db.session.add(Wishlist(user_id=user_id, product_id=product_id))
    db.session.commit()
    return jsonify({"success": True, "message": "Added to wishlist."}), 201

@user_auth_bp.route("/wishlist/<int:product_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@jwt_required()
def remove_from_wishlist(product_id):
    user_id = int(get_jwt_identity())
    item = Wishlist.query.filter_by(user_id=user_id, product_id=product_id).first()
    if not item:
        return jsonify({"success": False, "message": "Not in wishlist."}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"success": True, "message": "Removed from wishlist."}), 200

# ── FIREBASE CUSTOM TOKEN (for Firestore chat auth) ──────────────────────────
@user_auth_bp.route("/firebase-token", methods=["POST"])
@limiter.limit("20 per minute")
@jwt_required()
def get_user_firebase_token():
    """
    Mints a Firebase custom token tied to this user's identity,
    so the frontend can sign into Firestore and be recognized
    by security rules as this specific user.
    """
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    uid = f"user_{user.id}"
    custom_token = fb_auth.create_custom_token(uid)

    return jsonify({
        "success": True,
        "firebase_token": custom_token.decode("utf-8"),
        "uid": uid
    }), 200
    
@user_auth_bp.route("/chat/notify", methods=["POST"])
@jwt_required()
def notify_chat():
    import firebase_admin.firestore
    data     = request.get_json() or {}
    conv_id  = data.get('conv_id', '')
    text     = data.get('text', '')
    sender_role = data.get('sender_role', '')
    if not conv_id or not text:
        return jsonify({'success': False}), 400

    db_fs = firebase_admin.firestore.client()
    conv  = db_fs.collection('conversations').document(conv_id).get().to_dict()
    if not conv:
        return jsonify({'success': False}), 404

    if sender_role == 'user':
        vendor_id = int(conv.get('vendor_uid', '0').replace('vendor_', ''))
        v = Vendor.query.get(vendor_id)
        if v and v.fcm_token:
            send_chat_notification(v.fcm_token, conv.get('user_name') or 'User', text, conv_id)
    else:
        user_id = int(conv.get('user_uid', '0').replace('user_', ''))
        u = User.query.get(user_id)
        if u and u.fcm_token:
            send_chat_notification(u.fcm_token, conv.get('vendor_name') or 'Vendor', text, conv_id)

    return jsonify({'success': True}), 200