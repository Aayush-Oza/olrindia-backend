# OLR India - Vendor Auth Routes

import re
import bcrypt
from flask import Blueprint, request, jsonify, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity, unset_jwt_cookies
from datetime import datetime, timedelta
from models.payment import VendorPayment
from utils.razorpay_helper import create_order, verify_signature, fetch_payment
from extensions import db
from models.vendor import (
    Vendor, VendorVerificationToken, VendorPasswordResetToken,
    Product, PRODUCT_CATEGORIES, PLAN_LIMITS
)
from utils.email import send_verification_email, send_password_reset_email
from utils.token import generate_tokens, generate_access_token,_is_mobile
from utils.firebase_auth import verify_google_token
from utils.s3 import compress_and_upload, delete_from_s3
from utils.fcm import send_chat_notification
from models.user import User
from firebase_admin import auth as fb_auth
from routes.public import clear_public_cache
import utils.firebase_auth
import hmac
import hashlib
from flask import Blueprint, request, jsonify, make_response, current_app
from utils.firebase_auth import verify_google_token, sync_identity_to_conversations
from utils.plan_expiry_job import check_single_vendor
from extensions import limiter

vendor_auth_bp = Blueprint("vendor_auth", __name__)

# Plan rank helper - single source of truth used in payment logic
PLAN_RANK = {"free": 0, "starter": 1, "growth": 2, "premium": 3}


def validate_password(password, confirm_password):
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

def check_suspended(vendor):
    if vendor.is_suspended_for_strikes():
        return jsonify({
            "success": False,
            "suspended": True,
            "message": "Your account is suspended due to 3 policy violations. Contact support to get it reviewed."
        }), 403
    return None

def vendor_public_dict(vendor):
    return {
        "id": vendor.id,
        "name": vendor.name,
        "email": vendor.email,
        "profile_photo": vendor.profile_photo,
        "subscription_plan": vendor.effective_plan_name(),
        "badge": vendor.badge(),
        "has_verified_badge": vendor.has_verified_badge(),
        "max_active_posts": vendor.max_active_posts(),
        "active_product_count": vendor.active_product_count(),
        "pending_plan": vendor.pending_plan,
        "role": "vendor"
    }


# ── REGISTER ──────────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per hour")
def register():
    try:
        data = request.get_json()
        required = ["name", "email", "mobile", "pincode", "city", "state"]
        if not data.get("google_id"):
            required += ["password", "confirm_password"]
        for field in required:
            if not data.get(field):
                return jsonify({"success": False, "message": f"{field} is required."}), 400

        is_google = bool(data.get("google_id"))
        if not is_google:
            is_valid, error = validate_password(data["password"], data["confirm_password"])
            if not is_valid:
                return jsonify({"success": False, "message": error}), 400

        name          = data["name"].strip()
        email         = data["email"].strip().lower()
        mobile        = data["mobile"].strip()
        gst_number    = data.get("gst_number", "").strip() or None
        pincode       = data["pincode"].strip()
        city          = data["city"].strip()
        state         = data["state"].strip()
        area          = data.get("area", "").strip() or None

        if Vendor.query.filter_by(email=email).first():
            return jsonify({"success": False, "message": "An account with this email already exists."}), 409
        if Vendor.query.filter_by(mobile=mobile).first():
            return jsonify({"success": False, "message": "An account with this mobile number already exists."}), 409

        password_hash = None if is_google else bcrypt.hashpw(
            data["password"].encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        vendor = Vendor(
            name=name, email=email, mobile=mobile,
            password_hash=password_hash, 
            gst_number=gst_number, pincode=pincode, city=city, state=state, area=area,
            is_verified=False, subscription_plan="free",
        )
        db.session.add(vendor)
        db.session.flush()

        token_obj = VendorVerificationToken.generate(vendor.id)
        db.session.add(token_obj)
        db.session.commit()

        email_sent = send_verification_email(to_email=email, name=name, token=token_obj.token, role="vendor")
        if not email_sent:
            return jsonify({"success": True, "message": "Account created but email failed. Please use resend verification."}), 201

        return jsonify({"success": True, "message": "Vendor account created! Please check your email to verify your account."}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Registration failed.", "error": str(e)}), 500


# ── VERIFY EMAIL ──────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/verify-email", methods=["GET"])
@limiter.limit("10 per hour")
def verify_email():
    try:
        token = request.args.get("token")
        if not token:
            return jsonify({"success": False, "message": "Verification token is missing."}), 400
        token_obj = VendorVerificationToken.query.filter_by(token=token).first()
        if not token_obj:
            return jsonify({"success": False, "message": "Invalid verification link."}), 400
        if not token_obj.is_valid():
            return jsonify({"success": False, "message": "Link expired or already used."}), 400
        vendor = Vendor.query.get(token_obj.vendor_id)
        vendor.is_verified = True
        token_obj.is_used = True
        db.session.commit()
        return jsonify({"success": True, "message": "Email verified successfully! You can now login."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Verification failed.", "error": str(e)}), 500


# ── LOGIN ─────────────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute;50 per hour")
def login():
    try:
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        if not email or not password:
            return jsonify({"success": False, "message": "Email and password are required."}), 400
        vendor = Vendor.query.filter_by(email=email).first()
        if not vendor:
            return jsonify({"success": False, "message": "Invalid email or password."}), 401
        if not vendor.is_verified:
            return jsonify({"success": False, "message": "Please verify your email first.", "resend_verification": True}), 403
        if not bcrypt.checkpw(password.encode("utf-8"), vendor.password_hash.encode("utf-8")):
            return jsonify({"success": False, "message": "Invalid email or password."}), 401

        identity = {"id": vendor.id, "role": "vendor"}
        tokens = generate_tokens(identity)
        cookie_max_age = 365*24*60*60 if _is_mobile() else 7*24*60*60
        response = make_response(jsonify({"success": True, "message": "Login successful.", "vendor": vendor_public_dict(vendor)}), 200)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/vendor/"
        response.set_cookie("access_token_cookie",  tokens["access_token"],  httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,      path=cookie_path)
        response.set_cookie("refresh_token_cookie", tokens["refresh_token"], httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,  path=cookie_path)
        return response
    except Exception as e:
        return jsonify({"success": False, "message": "Login failed.", "error": str(e)}), 500


# ── REFRESH TOKEN ─────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/refresh", methods=["POST"])
@limiter.limit("30 per minute")
@jwt_required(refresh=True)
def refresh():
    try:
        identity = get_jwt_identity()
        new_access_token = generate_access_token(identity)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/vendor/"
        response = make_response(jsonify({"success": True, "message": "Token refreshed."}), 200)
        response.set_cookie("access_token_cookie", new_access_token, httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=15*60, path=cookie_path)
        return response
    except Exception as e:
        return jsonify({"success": False, "message": "Token refresh failed.", "error": str(e)}), 500


# ── LOGOUT ────────────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/logout", methods=["POST"])
def logout():
    response = make_response(jsonify({"success": True, "message": "Logged out successfully."}), 200)
    cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/vendor/"
    response.delete_cookie("access_token_cookie",  path=cookie_path)
    response.delete_cookie("refresh_token_cookie", path=cookie_path)
    return response


# ── FORGOT PASSWORD ───────────────────────────────────────────────────────────
@vendor_auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    try:
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        if not email:
            return jsonify({"success": False, "message": "Email is required."}), 400
        vendor = Vendor.query.filter_by(email=email).first()
        if not vendor:
            return jsonify({"success": True, "message": "If an account exists, a reset link has been sent."}), 200
        token_obj = VendorPasswordResetToken.generate(vendor.id)
        db.session.add(token_obj)
        db.session.commit()
        send_password_reset_email(to_email=email, name=vendor.name, token=token_obj.token, role="vendor")
        return jsonify({"success": True, "message": "If an account exists, a reset link has been sent."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Something went wrong.", "error": str(e)}), 500


# ── RESET PASSWORD ────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("5 per hour")
def reset_password():
    try:
        data = request.get_json()
        token = data.get("token", "").strip()
        new_password = data.get("new_password", "")
        confirm_password = data.get("confirm_password", "")
        if not token or not new_password or not confirm_password:
            return jsonify({"success": False, "message": "Token, new password and confirm password are required."}), 400
        is_valid, error = validate_password(new_password, confirm_password)
        if not is_valid:
            return jsonify({"success": False, "message": error}), 400
        token_obj = VendorPasswordResetToken.query.filter_by(token=token).first()
        if not token_obj or not token_obj.is_valid():
            return jsonify({"success": False, "message": "Invalid or expired reset link."}), 400
        vendor = Vendor.query.get(token_obj.vendor_id)
        vendor.password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        token_obj.is_used = True
        db.session.commit()
        return jsonify({"success": True, "message": "Password reset successfully."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Password reset failed.", "error": str(e)}), 500


# ── GOOGLE SIGN-IN ────────────────────────────────────────────────────────────
@vendor_auth_bp.route("/google", methods=["POST"])
@limiter.limit("10 per minute;50 per hour")
def google_login():
    try:
        data = request.get_json()
        id_token = (data or {}).get("id_token", "")
        google_data = verify_google_token(id_token)
        if not google_data:
            return jsonify({"success": False, "message": "Google sign-in failed. Invalid or expired token - please try again."}), 401

        email = google_data["email"]
        name  = google_data["name"]
        uid   = google_data["uid"]
        vendor = Vendor.query.filter_by(email=email).first()

        if not vendor:
            return jsonify({
                "success": True, "is_new_vendor": True,
                "message": "Complete your vendor registration to continue.",
                "google_prefill": {"name": name, "email": email, "google_id": uid}
            }), 200

        if not vendor.google_id:
            vendor.google_id = uid
            db.session.commit()

        if not vendor.is_verified:
            return jsonify({"success": False, "message": "Please verify your email first.", "resend_verification": True}), 403

        identity = {"id": vendor.id, "role": "vendor"}
        tokens = generate_tokens(identity)
        cookie_max_age = 365*24*60*60 if _is_mobile() else 7*24*60*60  # ADD THIS
        response = make_response(jsonify({"success": True, "is_new_vendor": False, "message": "Google sign-in successful.", "vendor": vendor_public_dict(vendor)}), 200)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/vendor/"
        response.set_cookie("access_token_cookie",  tokens["access_token"],  httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age,      path=cookie_path)
        response.set_cookie("refresh_token_cookie", tokens["refresh_token"], httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=cookie_max_age, path=cookie_path)
        return response
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": "Google sign-in failed.", "error": str(e)}), 500


# ── VENDOR PROFILE ────────────────────────────────────────────
@vendor_auth_bp.route("/profile", methods=["GET"])
@limiter.limit("60 per minute")
@jwt_required()
def get_profile():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v:
        return jsonify({"success": False, "message": "Vendor not found."}), 404
    check_single_vendor(v)  # Instant expiry check on profile load
    return jsonify({"success": True, "vendor": {
        "id": v.id, "name": v.name, "email": v.email,
        "mobile": v.mobile, 
        "gst_number": v.gst_number,
        "pincode": v.pincode, "area": v.area, "city": v.city, "state": v.state,
        "profile_photo": v.profile_photo,
        "subscription_plan": v.effective_plan_name(),
        "badge": v.badge(),
        "has_verified_badge": v.has_verified_badge(),
        "max_active_posts": v.max_active_posts(),
        "active_product_count": v.active_product_count(),
        "subscription_expires_at": str(v.subscription_expires_at) if v.subscription_expires_at else None,
        "is_verified": v.is_verified, "created_at": str(v.created_at),
        "is_active": v.is_active,
        "days_until_expiry": v.days_until_expiry(),
        "show_expiry_banner": v.should_show_expiry_banner(),
        "suspended_reason": v.suspended_reason,
        "pending_plan": v.pending_plan,
    }}), 200
    
@vendor_auth_bp.route("/profile", methods=["PUT"])
@limiter.limit("20 per minute")
@jwt_required()
def update_profile():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v:
        return jsonify({"success": False, "message": "Vendor not found."}), 404
    suspended = check_suspended(v)
    if suspended: return suspended
    data = request.get_json()
    if data.get("name"):          v.name          = data["name"].strip()
    if data.get("mobile"):
        existing = Vendor.query.filter(Vendor.mobile == data["mobile"].strip(), Vendor.id != v.id).first()
        if existing:
            return jsonify({"success": False, "message": "Mobile already linked to another account."}), 409
        v.mobile = data["mobile"].strip()
    if data.get("gst_number"):    v.gst_number    = data["gst_number"].strip()
    if data.get("pincode"):       v.pincode       = data["pincode"].strip()
    if data.get("area"):          v.area          = data["area"].strip()
    if data.get("city"):          v.city          = data["city"].strip()
    if data.get("state"):         v.state         = data["state"].strip()
    db.session.commit()
    sync_identity_to_conversations('vendor', v.id, v.name, v.profile_photo)
    return jsonify({"success": True, "message": "Profile updated."}), 200


# ── PROFILE PHOTO ─────────────────────────────────────────────
@vendor_auth_bp.route("/profile/photo", methods=["PUT"])
@limiter.limit("10 per hour")
@jwt_required()
def update_profile_photo():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404
    suspended = check_suspended(v)
    if suspended: return suspended
    f = request.files.get("photo")
    if not f: return jsonify({"success": False, "message": "No photo provided."}), 400
    old_url = v.profile_photo
    url = compress_and_upload(f, folder="vendor-profiles")
    if not url: return jsonify({"success": False, "message": "Photo upload failed."}), 500
    v.profile_photo = url
    db.session.commit()
    if old_url: delete_from_s3(old_url)
    sync_identity_to_conversations('vendor', v.id, v.name, v.profile_photo)
    return jsonify({"success": True, "message": "Profile photo updated.", "url": url}), 200

@vendor_auth_bp.route("/profile/photo", methods=["DELETE"])
@limiter.limit("10 per hour")
@jwt_required()
def delete_profile_photo():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404
    suspended = check_suspended(v)
    if suspended: return suspended
    if v.profile_photo:
        delete_from_s3(v.profile_photo)
        v.profile_photo = None
        db.session.commit()
    sync_identity_to_conversations('vendor', v.id, v.name, None)
    return jsonify({"success": True, "message": "Profile photo removed."}), 200


# ── PRODUCTS ──────────────────────────────────────────────────
@vendor_auth_bp.route("/products", methods=["GET"])
@limiter.limit("60 per minute")
@jwt_required()
def get_products():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404
    products = Product.query.filter_by(vendor_id=vendor_id).order_by(Product.created_at.desc()).all()
    return jsonify({
        "success": True,
        "products": [p.to_dict() for p in products],
        "expiry_banner": {
            "show": v.should_show_expiry_banner(),
            "days_left": v.days_until_expiry(),
            "plan": v.effective_plan_name(),
            "message": (
                f"Your {v.effective_plan_name().capitalize()} plan expires in "
                f"{v.days_until_expiry()} day(s)! Renew now to keep all listings active."
            ) if v.should_show_expiry_banner() else None
        }
    }), 200

@vendor_auth_bp.route("/categories", methods=["GET"])
def get_categories():
    return jsonify({"success": True, "categories": PRODUCT_CATEGORIES}), 200

@vendor_auth_bp.route("/plans", methods=["GET"])
def get_plans():
    return jsonify({"success": True, "plans": PLAN_LIMITS}), 200

@vendor_auth_bp.route("/products", methods=["POST"])
@limiter.limit("20 per hour")
@jwt_required()
def add_product():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404
    suspended = check_suspended(v)
    if suspended: return suspended

    can_post, limit_error = v.can_add_product()
    if not can_post: return jsonify({"success": False, "message": limit_error}), 403

    name = request.form.get("name", "").strip()
    if not name: return jsonify({"success": False, "message": "name is required."}), 400


    rent_per_hour_raw  = request.form.get("rent_per_hour", "").strip()
    rent_per_km_raw    = request.form.get("rent_per_km", "").strip()
    rent_per_day_raw   = request.form.get("rent_per_day", "").strip()
    rent_per_month_raw = request.form.get("rent_per_month", "").strip()
    if not rent_per_hour_raw and not rent_per_km_raw and not rent_per_day_raw and not rent_per_month_raw:
        return jsonify({"success": False, "message": "Please provide at least one rent rate (per hour, km, day, or month)."}), 400

    category = request.form.get("category", "").strip()
    if category not in PRODUCT_CATEGORIES:
        return jsonify({"success": False, "message": "Invalid category."}), 400
    subcategory = request.form.get("subcategory", "").strip() or None

    urls = []
    for i in range(1, 6):
        f = request.files.get(f"image{i}")
        if f:
            url = compress_and_upload(f, folder="products")
            if not url: return jsonify({"success": False, "message": f"Image {i} upload failed."}), 500
            urls.append(url)
    if not urls: return jsonify({"success": False, "message": "At least one image is required."}), 400
    urls += [None] * (5 - len(urls))

    share_slug = Product.generate_share_slug()
    while Product.query.filter_by(share_slug=share_slug).first():
        share_slug = Product.generate_share_slug()

    p = Product(
        vendor_id=vendor_id, name=name,
        description=request.form.get("description", "").strip() or None,
        rent_per_hour=float(rent_per_hour_raw) if rent_per_hour_raw else None,
        rent_per_km=float(rent_per_km_raw) if rent_per_km_raw else None,
        rent_per_day=float(rent_per_day_raw) if rent_per_day_raw else None,
        rent_per_month=float(rent_per_month_raw) if rent_per_month_raw else None,
        security_deposit=float(request.form.get("security_deposit")) if request.form.get("security_deposit") else None,
        pincode=request.form.get("pincode") or v.pincode,
        state=request.form.get("state") or v.state,
        city=request.form.get("city") or v.city,
        area=request.form.get("area") or v.area,
        category=category, subcategory=subcategory,
        image1=urls[0], image2=urls[1], image3=urls[2],
        image4=urls[3], image5=urls[4],
        share_slug=share_slug,
    )
    db.session.add(p)
    db.session.commit()
    clear_public_cache()
    return jsonify({"success": True, "message": "Product listed!", "product": p.to_dict()}), 201


@vendor_auth_bp.route("/products/<int:product_id>", methods=["PUT"])
@limiter.limit("30 per hour")
@jwt_required()
def update_product(product_id):
    vendor_id = int(get_jwt_identity())
    p = Product.query.filter_by(id=product_id, vendor_id=vendor_id).first()
    if not p: return jsonify({"success": False, "message": "Product not found."}), 404
    v = Vendor.query.get(vendor_id)
    suspended = check_suspended(v)
    if suspended: return suspended
    data = request.get_json()

    def to_float_or_none(val):
        if val is None or val == '': return None
        try: return float(val)
        except: return None

    if 'name' in data and data['name']:         p.name             = data['name'].strip()
    if 'description' in data:                   p.description      = data['description'] or None
    if 'rent_per_hour' in data:                  p.rent_per_hour    = to_float_or_none(data['rent_per_hour'])
    if 'rent_per_km' in data:                    p.rent_per_km      = to_float_or_none(data['rent_per_km'])
    if 'rent_per_day' in data:                  p.rent_per_day     = to_float_or_none(data['rent_per_day'])
    if 'rent_per_month' in data:                p.rent_per_month   = to_float_or_none(data['rent_per_month'])
    if 'security_deposit' in data:              p.security_deposit = to_float_or_none(data['security_deposit'])
    if 'category' in data and data['category']: p.category         = data['category']
    if 'subcategory' in data:                   p.subcategory      = data['subcategory'] or None
    if 'pincode' in data:                       p.pincode          = data['pincode'] or None
    if 'area' in data:                          p.area             = data['area'] or None
    if 'city' in data:                          p.city             = data['city'] or None
    if 'state' in data:                         p.state            = data['state'] or None
    if p.deactivated_by == "admin":
        p.is_active = True
        p.deactivated_by = None
        p.edit_deadline = None
    p.admin_reviewed = False
    db.session.commit()
    clear_public_cache()
    return jsonify({"success": True, "message": "Product updated.", "product": p.to_dict()}), 200


@vendor_auth_bp.route("/products/<int:product_id>/status", methods=["PUT"])
@limiter.limit("30 per minute")
@jwt_required()
def update_product_status(product_id):
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    p = Product.query.filter_by(id=product_id, vendor_id=vendor_id).first()
    if not p: return jsonify({"success": False, "message": "Product not found."}), 404
    suspended = check_suspended(v)
    if suspended: return suspended
    data = request.get_json()
    if not p.is_active and p.deactivated_by == "admin":
        return jsonify({"success": False, "message": "This product was deactivated by admin. Edit it to bring it back live."}), 403
    if not p.is_active and p.deactivated_by == "plan_expired":
        return jsonify({"success": False, "message": "This product was deactivated because your plan expired. Renew your plan to reactivate all products."}), 403
    if "is_active" not in data:
        return jsonify({"success": False, "message": "is_active is required."}), 400
    new_status = bool(data["is_active"])
    if new_status and not p.is_active:
        can_post, limit_error = v.can_add_product()
        if not can_post: return jsonify({"success": False, "message": limit_error}), 403
    p.is_active = new_status
    p.last_availability_check = db.func.now()
    db.session.commit()
    clear_public_cache()
    return jsonify({"success": True, "message": "Product status updated.", "product": p.to_dict()}), 200


@vendor_auth_bp.route("/products/<int:product_id>/image/<int:slot>", methods=["PUT"])
@limiter.limit("20 per hour")
@jwt_required()
def update_product_image(product_id, slot):
    if slot < 1 or slot > 5: return jsonify({"success": False, "message": "Slot must be 1-5."}), 400
    vendor_id = int(get_jwt_identity())
    p = Product.query.filter_by(id=product_id, vendor_id=vendor_id).first()
    if not p: return jsonify({"success": False, "message": "Product not found."}), 404
    v = Vendor.query.get(vendor_id)
    suspended = check_suspended(v)
    if suspended: return suspended
    f = request.files.get("image")
    if not f: return jsonify({"success": False, "message": "No image provided."}), 400
    old_url = getattr(p, f"image{slot}")
    if old_url: delete_from_s3(old_url)
    url = compress_and_upload(f, folder="products")
    if not url: return jsonify({"success": False, "message": "Upload failed."}), 500
    setattr(p, f"image{slot}", url)
    db.session.commit()
    return jsonify({"success": True, "message": "Image updated.", "url": url}), 200


@vendor_auth_bp.route("/products/<int:product_id>/image/<int:slot>", methods=["DELETE"])
@limiter.limit("20 per hour")
@jwt_required()
def delete_product_image(product_id, slot):
    if slot < 1 or slot > 5: return jsonify({"success": False, "message": "Slot must be 1-5."}), 400
    vendor_id = int(get_jwt_identity())
    p = Product.query.filter_by(id=product_id, vendor_id=vendor_id).first()
    if not p: return jsonify({"success": False, "message": "Product not found."}), 404
    v = Vendor.query.get(vendor_id)
    suspended = check_suspended(v)
    if suspended: return suspended
    old_url = getattr(p, f"image{slot}")
    if old_url:
        delete_from_s3(old_url)
        setattr(p, f"image{slot}", None)
        db.session.commit()
    return jsonify({"success": True, "message": "Image deleted."}), 200


@vendor_auth_bp.route("/products/<int:product_id>", methods=["DELETE"])
@limiter.limit("20 per hour")
@jwt_required()
def delete_product(product_id):
    vendor_id = int(get_jwt_identity())
    p = Product.query.filter_by(id=product_id, vendor_id=vendor_id).first()
    if not p: return jsonify({"success": False, "message": "Product not found."}), 404
    v = Vendor.query.get(vendor_id)
    suspended = check_suspended(v)
    if suspended: return suspended
    for url in p.image_urls(): delete_from_s3(url)
    db.session.delete(p)
    db.session.commit()
    clear_public_cache()
    return jsonify({"success": True, "message": "Product deleted."}), 200


@vendor_auth_bp.route("/products/<int:product_id>/click", methods=["POST"])
@limiter.limit("5 per minute")
def record_click(product_id):
    p = Product.query.get(product_id)
    if not p: return jsonify({"success": False}), 404
    p.click_count += 1
    db.session.commit()
    return jsonify({"success": True}), 200

@vendor_auth_bp.route("/firebase-token", methods=["POST"])
@limiter.limit("20 per minute")
@jwt_required()
def get_vendor_firebase_token():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404
    uid = f"vendor_{v.id}"
    custom_token = fb_auth.create_custom_token(uid)
    return jsonify({"success": True, "firebase_token": custom_token.decode("utf-8"), "uid": uid}), 200


# ── SUBSCRIBE: Vendor selects a plan → create Razorpay order ─────────────────
@vendor_auth_bp.route("/subscribe", methods=["POST"])
@limiter.limit("10 per hour")
@jwt_required()
def subscribe():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404
    suspended = check_suspended(v)
    if suspended: return suspended

    data = request.get_json()
    plan = (data or {}).get("plan", "").strip().lower()
    if plan not in ("starter", "growth", "premium"):
        return jsonify({"success": False, "message": "Invalid plan. Choose starter, growth, or premium."}), 400

    plan_info  = PLAN_LIMITS[plan]
    amount_inr = plan_info["price"]
    if v.pending_plan is not None:
        return jsonify({"success": False, "message": f"You already have a plan change to {v.pending_plan.capitalize()} scheduled. Please wait until it activates."}), 409

    # reuse or cancel any already-open order for this vendor
    existing = VendorPayment.query.filter_by(vendor_id=vendor_id, status="created").order_by(VendorPayment.id.desc()).first()
    if existing:
        if existing.plan == plan:
            plan_info = PLAN_LIMITS[plan]
            return jsonify({
                "success": True, "order_id": existing.razorpay_order_id,
                "amount": int(existing.amount_inr) * 100, "currency": "INR",
                "key_id": current_app.config["RAZORPAY_KEY_ID"],
                "vendor": {"name": v.name, "email": v.email},
                "plan_label": plan_info["label"], "reused_existing_order": True,
            }), 200
        else:
            existing.status = "cancelled"
            db.session.commit()
            
    order = create_order(amount_inr, plan, vendor_id)
    if not order:
        return jsonify({"success": False, "message": "Could not initiate payment. Please try again."}), 500

    payment = VendorPayment(
        vendor_id=vendor_id, plan=plan, amount_inr=amount_inr,
        razorpay_order_id=order["id"], status="created", duration_days=30,
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "success":    True,
        "order_id":   order["id"],
        "amount":     order["amount"],
        "currency":   order["currency"],
        "key_id":     current_app.config["RAZORPAY_KEY_ID"],
        "vendor":     {"name": v.name, "email": v.email},
        "plan_label": plan_info["label"],
    }), 200


# ── PAYMENT VERIFY: Frontend sends payment proof → activate plan ──────────────
@vendor_auth_bp.route("/payment/verify", methods=["POST"])
@limiter.limit("10 per hour")
@jwt_required()
def verify_payment():
    """
    Plan transition rules
    ─────────────────────────────────────────────────────────────────
    CASE A  No active paid plan (free/expired/trial):
              Activate new plan immediately. Expiry = now + 30 days.

    CASE B  Active plan + buying HIGHER plan (upgrade):
              Switch plan now. Extend expiry by 30 days from current expiry.
              Vendor keeps remaining days on old plan - nothing is lost.

    CASE C  Active plan + buying SAME plan (renewal):
              Keep plan. Extend expiry by 30 days from current expiry.

    CASE D  Active plan + buying LOWER plan (downgrade):
              DO NOT switch plan yet. Store as pending_plan.
              Extend expiry by 30 days from current expiry.
              plan_expiry_job activates pending_plan at next cycle end.
              Vendor keeps higher plan for remainder of current cycle.
    ─────────────────────────────────────────────────────────────────
    """
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v: return jsonify({"success": False, "message": "Vendor not found."}), 404

    data       = request.get_json() or {}
    order_id   = data.get("razorpay_order_id", "").strip()
    payment_id = data.get("razorpay_payment_id", "").strip()
    signature  = data.get("razorpay_signature", "").strip()

    if not order_id or not payment_id or not signature:
        return jsonify({"success": False, "message": "razorpay_order_id, razorpay_payment_id and razorpay_signature are all required."}), 400

    payment = VendorPayment.query.filter_by(
        razorpay_order_id=order_id, vendor_id=vendor_id, status="created"
    ).with_for_update().first()
    if not payment:
        return jsonify({"success": False, "message": "Order not found or already processed."}), 404

    if not verify_signature(order_id, payment_id, signature):
        payment.status = "failed"
        db.session.commit()
        return jsonify({"success": False, "message": "Payment verification failed. Please contact support."}), 400

    razorpay_payment = fetch_payment(payment_id)
    expected_paise = int(payment.amount_inr) * 100
    if not razorpay_payment or razorpay_payment.get("amount") != expected_paise:
        payment.status = "failed"
        db.session.commit()
        return jsonify({"success": False, "message": "Amount mismatch. Please contact support."}), 400

    # ── Signature valid ───────────────────────────────────────────────────────
    now = datetime.utcnow()
    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature  = signature
    payment.status              = "paid"
    payment.paid_at             = now

    new_plan     = payment.plan
    new_rank     = PLAN_RANK.get(new_plan, 0)
    current_plan = v.effective_plan_name()   # accounts for expiry → "free"
    current_rank = PLAN_RANK.get(current_plan, 0)

    # An "active" paid plan means: paid tier, not expired
    plan_is_active = (
        v.subscription_expires_at is not None and
        v.subscription_expires_at > now and
        current_plan not in ("free")
    )

    if not plan_is_active:
        # CASE A - No active paid plan
        v.subscription_plan       = new_plan
        v.subscription_expires_at = now + timedelta(days=payment.duration_days)
        v.pending_plan            = None
        payment.period_start      = now
        payment.period_end        = v.subscription_expires_at
        transition = "activated"

    elif new_rank > current_rank:
        # CASE B - Upgrade: queue for next cycle
        old_expiry           = v.subscription_expires_at
        v.pending_plan       = new_plan
        payment.period_start = old_expiry
        payment.period_end   = old_expiry + timedelta(days=payment.duration_days)
        transition = "pending_upgrade"

    elif new_rank == current_rank:
        # CASE C - Same plan renewal
        v.subscription_plan       = new_plan
        v.subscription_expires_at = v.subscription_expires_at + timedelta(days=payment.duration_days)
        v.pending_plan            = None
        payment.period_start      = v.subscription_expires_at - timedelta(days=payment.duration_days)
        payment.period_end        = v.subscription_expires_at
        transition = "renewed"


    else:
        # CASE D - Downgrade: keep current plan, queue new one
        # Do NOT touch subscription_plan or subscription_expires_at
        old_expiry           = v.subscription_expires_at
        v.pending_plan       = new_plan
        payment.period_start = old_expiry  # starts after current plan ends
        payment.period_end   = old_expiry + timedelta(days=payment.duration_days)
        transition = "pending_downgrade"

    # Reactivate plan_expired products for any case except downgrade
    if transition not in ("pending_downgrade", "pending_upgrade"):
        Product.query.filter_by(
            vendor_id=vendor_id, is_active=False, deactivated_by="plan_expired"
        ).update({"is_active": True, "deactivated_by": None})

    db.session.commit()

    # Human-readable message
    expiry_str = v.subscription_expires_at.strftime("%-d %B %Y") if v.subscription_expires_at else ""
    if transition == "activated":
        msg = f"You're now on the {new_plan.capitalize()} plan! Active until {expiry_str}."
    elif transition == "upgraded":
        msg = f"Upgraded to {new_plan.capitalize()}! Your plan is active until {expiry_str}."
    elif transition == "renewed":
        msg = f"{new_plan.capitalize()} plan renewed. Active until {expiry_str}."
    elif transition == "pending_upgrade":
        msg = (
            f"Payment confirmed. You'll stay on {current_plan.capitalize()} until {expiry_str}, "
            f"then upgrade to {new_plan.capitalize()} at the next cycle."
        )
    else:
        msg = (
            f"Payment confirmed. You'll stay on {current_plan.capitalize()} until {expiry_str}, "
            f"then switch to {new_plan.capitalize()} at the next cycle."
        )

    return jsonify({
        "success":    True,
        "message":    msg,
        "transition": transition,
        "vendor":     vendor_public_dict(v),
        "expires_at": str(v.subscription_expires_at),
    }), 200


# ── RAZORPAY WEBHOOK ──────────────────────────────────────────────────────────
@vendor_auth_bp.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    """
    Razorpay calls this directly when payment succeeds.
    Uses the same 4-case transition logic as /payment/verify.
    Safe to run even if /payment/verify already processed it.
    """
    webhook_secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET", "")
    received_sig   = request.headers.get("X-Razorpay-Signature", "")
    body           = request.get_data()

    expected_sig = hmac.new(
        key=webhook_secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, received_sig):
        return jsonify({"success": False, "message": "Invalid signature."}), 400

    payload = request.get_json()
    if payload.get("event") != "payment.captured":
        return jsonify({"success": True, "message": "Event ignored."}), 200

    order_id = payload["payload"]["payment"]["entity"]["order_id"]
    payment  = VendorPayment.query.filter_by(razorpay_order_id=order_id, status="created").with_for_update().first()
    if not payment:
        return jsonify({"success": True, "message": "Already processed."}), 200

    payment_entity = payload["payload"]["payment"]["entity"]
    expected_paise = int(payment.amount_inr) * 100
    if payment_entity.get("amount") != expected_paise:
        payment.status = "failed"
        db.session.commit()
        return jsonify({"success": False, "message": "Amount mismatch."}), 400

    now = datetime.utcnow()
    payment.razorpay_payment_id = payload["payload"]["payment"]["entity"]["id"]
    payment.status  = "paid"
    payment.paid_at = now

    v = Vendor.query.get(payment.vendor_id)
    if v:
        new_plan     = payment.plan
        new_rank     = PLAN_RANK.get(new_plan, 0)
        current_plan = v.effective_plan_name()
        current_rank = PLAN_RANK.get(current_plan, 0)

        plan_is_active = (
            v.subscription_expires_at is not None and
            v.subscription_expires_at > now and
            current_plan not in ("free")
        )

        if not plan_is_active:
            v.subscription_plan       = new_plan
            v.subscription_expires_at = now + timedelta(days=payment.duration_days)
            v.pending_plan            = None
            reactivate = True
            payment.period_start = now
            payment.period_end   = v.subscription_expires_at
        elif new_rank > current_rank:
            old_expiry           = v.subscription_expires_at
            v.pending_plan       = new_plan
            payment.period_start = old_expiry
            payment.period_end   = old_expiry + timedelta(days=payment.duration_days)
            reactivate = False
        elif new_rank == current_rank:
            v.subscription_plan       = new_plan
            v.subscription_expires_at = v.subscription_expires_at + timedelta(days=payment.duration_days)
            v.pending_plan            = None
            reactivate = True
            payment.period_start = v.subscription_expires_at - timedelta(days=payment.duration_days)
            payment.period_end   = v.subscription_expires_at
        else:
            old_expiry           = v.subscription_expires_at
            v.pending_plan       = new_plan
            payment.period_start = old_expiry
            payment.period_end   = old_expiry + timedelta(days=payment.duration_days)
            reactivate = False

        if reactivate:
            Product.query.filter_by(
                vendor_id=v.id, is_active=False, deactivated_by="plan_expired"
            ).update({"is_active": True, "deactivated_by": None})

    db.session.commit()
    return jsonify({"success": True}), 200

@vendor_auth_bp.route("/billing", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_billing():
    vendor_id = int(get_jwt_identity())
    now = datetime.utcnow()

    all_payments = VendorPayment.query.filter_by(
        vendor_id=vendor_id, status="paid"
    ).order_by(VendorPayment.period_start.asc()).all()

    history = []
    past_added = 0

    for p in all_payments:
        period_end = p.period_end
        period_start = p.period_start

        is_current = period_start and period_end and period_start <= now <= period_end
        is_future  = period_start and period_start > now
        is_past    = period_end and period_end < now

        # Only include: last 1 past, current, all future
        if is_past:
            past_added += 1
            # We'll filter to only last 1 past after loop
        
        history.append({
            "plan":         p.plan,
            "amount_inr":   str(p.amount_inr),
            "period_start": str(period_start) if period_start else None,
            "period_end":   str(period_end)   if period_end   else None,
            "paid_at":      str(p.paid_at)    if p.paid_at    else None,
            "is_current":   is_current,
            "is_future":    is_future,
            "is_past":      is_past,
        })

    # Keep only last 1 past + current + all future
    past_seen = 0
    filtered = []
    for item in reversed(history):
        if item["is_past"]:
            if past_seen < 1:
                filtered.append(item)
                past_seen += 1
        else:
            filtered.append(item)

    filtered = list(reversed(filtered))

    return jsonify({"success": True, "billing": filtered}), 200

@vendor_auth_bp.route("/chat/notify", methods=["POST"])
@jwt_required()
def vendor_notify_chat():
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
            send_chat_notification(v.fcm_token, conv.get('user_name') or 'User', text, conv_id, conv.get('user_photo'))
    else:
        user_id = int(conv.get('user_uid', '0').replace('user_', ''))
        u = User.query.get(user_id)
        if u and u.fcm_token:
            send_chat_notification(u.fcm_token, conv.get('vendor_name') or 'Vendor', text, conv_id, conv.get('vendor_photo'))

    return jsonify({'success': True}), 200

@vendor_auth_bp.route("/fcm-token", methods=["POST"])
@limiter.limit("20 per minute")
@jwt_required()
def save_fcm_token():
    vendor_id = int(get_jwt_identity())
    v = Vendor.query.get(vendor_id)
    if not v:
        return jsonify({"success": False}), 404
    data = request.get_json() or {}
    token = data.get("fcm_token", "").strip()
    if not token:
        return jsonify({"success": False, "message": "Missing token"}), 400
    v.fcm_token = token
    db.session.commit()
    return jsonify({"success": True}), 200