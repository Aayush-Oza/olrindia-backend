# OLR India - Admin Auth Routes
# No signup - admin rows are created manually via direct DB inserts.
# POST /auth/admin/login
# POST /auth/admin/refresh
# POST /auth/admin/logout
# GET  /auth/admin/profile

import bcrypt
from flask import Blueprint, request, jsonify, make_response, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, unset_jwt_cookies
from datetime import datetime, timedelta
from extensions import limiter

from extensions import db
from models.admin import Admin

from utils.token import generate_tokens, generate_access_token
from utils.email import send_vendor_strike_email, send_vendor_suspended_email, send_vendor_reactivated_email
admin_auth_bp = Blueprint("admin_auth", __name__)


# ── LOGIN ─────────────────────────────────────────────────────────────────────
@admin_auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute;20 per hour")
def login():
    try:
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")

        if not email or not password:
            return jsonify({"success": False, "message": "Email and password are required."}), 400

        admin = Admin.query.filter_by(email=email).first()
        if not admin:
            return jsonify({"success": False, "message": "Invalid email or password."}), 401

        if not admin.is_active:
            return jsonify({"success": False, "message": "This admin account has been deactivated."}), 403

        if not bcrypt.checkpw(password.encode("utf-8"), admin.password_hash.encode("utf-8")):
            return jsonify({"success": False, "message": "Invalid email or password."}), 401

        identity = {"id": admin.id, "role": "admin"}
        tokens = generate_tokens(identity)

        response = make_response(jsonify({
            "success": True,
            "message": "Login successful.",
            "admin": {
                "id": admin.id,
                "name": admin.name,
                "email": admin.email,
                "role": "admin",
            }
        }), 200)

        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/admin/"
        response.set_cookie("access_token_cookie", tokens["access_token"],
                           httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=15*60, path=cookie_path)
        response.set_cookie("refresh_token_cookie", tokens["refresh_token"],
                           httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=7*24*60*60, path=cookie_path)

        return response

    except Exception as e:
        return jsonify({"success": False, "message": "Login failed.", "error": str(e)}), 500


# ── REFRESH TOKEN ─────────────────────────────────────────────────────────────
@admin_auth_bp.route("/refresh", methods=["POST"])
@limiter.limit("20 per minute")
@jwt_required(refresh=True)
def refresh():
    try:
        identity = get_jwt_identity()
        new_access_token = generate_access_token(identity)

        response = make_response(jsonify({"success": True, "message": "Token refreshed."}), 200)
        cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/admin/"
        response.set_cookie("access_token_cookie", new_access_token,
                           httponly=True, secure=current_app.config.get("JWT_COOKIE_SECURE", False), samesite="Lax", max_age=15*60, path=cookie_path)
        return response

    except Exception as e:
        return jsonify({"success": False, "message": "Token refresh failed.", "error": str(e)}), 401


# ── LOGOUT ────────────────────────────────────────────────────────────────────
@admin_auth_bp.route("/logout", methods=["POST"])
def logout():
    response = make_response(jsonify({"success": True, "message": "Logged out successfully."}), 200)
    cookie_path = current_app.config.get("API_URL_PREFIX", "") + "/auth/admin/"
    unset_jwt_cookies(response, path=cookie_path)
    return response


# ── GET PROFILE ───────────────────────────────────────────────────────────────
@admin_auth_bp.route("/profile", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_profile():
    admin_id = int(get_jwt_identity())
    admin = Admin.query.get(admin_id)
    if not admin:
        return jsonify({"success": False, "message": "Admin not found."}), 404
    return jsonify({"success": True, "admin": {
        "id": admin.id, "name": admin.name, "email": admin.email,
        "created_at": str(admin.created_at)
    }}), 200
    
from models.user import User
from models.vendor import Vendor, Product, VendorStrike

# ── DASHBOARD STATS ────────────────────────────────────────────────────────
@admin_auth_bp.route("/stats", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_stats():
    total_users = User.query.count()
    total_vendors = Vendor.query.count()
    total_products = Product.query.count()
    active_products = Product.query.filter_by(is_active=True).count()
    flagged_vendors = Vendor.query.filter(Vendor.strike_count > 0).count()
    suspended_vendors = Vendor.query.filter_by(suspended_reason="strikes", is_active=False).count()

    return jsonify({
        "success": True,
        "stats": {
            "total_users": total_users,
            "total_vendors": total_vendors,
            "total_products": total_products,
            "active_products": active_products,
            "flagged_vendors": flagged_vendors,
            "suspended_vendors": suspended_vendors,
        }
    }), 200
    
# ── USERS LIST ───────────────────────────────────────────────────────────────
@admin_auth_bp.route("/users", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_users():
    search = request.args.get("search", "").strip()
    city = request.args.get("city", "").strip()
    area = request.args.get("area", "").strip()
    state = request.args.get("state", "").strip()
    page  = request.args.get("page", 1, type=int)
    per_page = 15

    query = User.query

    if search:
        query = query.filter(
            db.or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )

    if city:
        query = query.filter(User.city.ilike(f"%{city}%"))

    if area:
        query = query.filter(User.area.ilike(f"%{area}%"))

    if state:
        query = query.filter(User.state.ilike(f"%{state}%"))
    query = query.order_by(User.created_at.desc())
    total = query.count()
    users = query.order_by(User.created_at.desc()).all()

    return jsonify({
        "success": True,
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": (page * per_page) < len(users),
        "users": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "mobile": u.mobile,
                "city": u.city,
                "area": u.area,
                "state": u.state,
                "created_at": u.created_at.strftime("%d %b %Y")
            }
            for u in users
        ]
    }), 200
    
# ── PRODUCTS LIST ────────────────────────────────────────────────────────────
@admin_auth_bp.route("/products", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_products():
    search   = request.args.get("search", "").strip()
    status   = request.args.get("status", "").strip()
    reviewed = request.args.get("reviewed", "").strip()   # <-- NEW
    page     = request.args.get("page", 1, type=int)
    per_page = 15

    query = Product.query.join(Vendor)

    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f"%{search}%"),
                Vendor.name.ilike(f"%{search}%"),
            )
        )

    if status == "active":
        query = query.filter(Product.is_active == True)
    elif status == "inactive":
        query = query.filter(Product.is_active == False)

    if reviewed == "viewed":                              # <-- NEW
        query = query.filter(Product.admin_reviewed == True)
    elif reviewed == "unviewed":
        query = query.filter(Product.admin_reviewed == False)
    query = query.order_by(Product.created_at.desc())
    total = query.count()
    products = query.order_by(Product.created_at.desc()).all()

    return jsonify({
        "success": True,
        "page": page,
        "total": total,
        "has_more": (page * per_page) < total,
        "products": [
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "vendor_name": p.vendor.name,
                "city": p.city,
                "state": p.state,
                "image": p.image1,
                "active": p.is_active,
                "clicks": p.click_count,
                "created_at": p.created_at.strftime("%d %b %Y"),
                "slug": p.share_slug,
                "reviewed": p.admin_reviewed,               # <-- NEW
            }
            for p in products
        ]
    }), 200
    
# ── VENDORS LIST ─────────────────────────────────────────────────────────────
@admin_auth_bp.route("/vendors", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_vendors():

    search = request.args.get("search", "").strip()
    city = request.args.get("city", "").strip()
    area = request.args.get("area", "").strip()
    state = request.args.get("state", "").strip()
    plan = request.args.get("plan", "").strip()
    flag = request.args.get("flag", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 15

    query = Vendor.query

    if search:
        query = query.filter(
            db.or_(
                Vendor.name.ilike(f"%{search}%"),
                Vendor.email.ilike(f"%{search}%"),
            )
        )

    if city:
        query = query.filter(Vendor.city.ilike(f"%{city}%"))

    if area:
        query = query.filter(Vendor.area.ilike(f"%{area}%"))

    if state:
        query = query.filter(Vendor.state.ilike(f"%{state}%"))

    if plan:
        query = query.filter(Vendor.subscription_plan == plan)

    if flag == "flagged":
        query = query.filter(Vendor.strike_count > 0)

    elif flag == "suspended":
        query = query.filter(Vendor.is_active == False)
    elif flag == "active":
        query = query.filter(Vendor.is_active == True)
    query = query.order_by(Vendor.created_at.desc())
    total = query.count()
    vendors = query.order_by(Vendor.created_at.desc()).all()

    return jsonify({
        "success": True,
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": (page * per_page) < total,
        "vendors": [
            {
                "id": v.id,
                "name": v.name,
                "email": v.email,
                "mobile": v.mobile,
                "city": v.city,
                "area": v.area,
                "state": v.state,
                "plan": v.subscription_plan,
                "verified": v.is_verified,
                "active": v.is_active,
                "strike_count": v.strike_count,
                "created_at": v.created_at.strftime("%d %b %Y")
            }
            for v in vendors
        ]
    }), 200
    
# ── REMOVE PRODUCT (issues a strike to the vendor) ──────────────────────────
@admin_auth_bp.route("/products/<int:product_id>/remove", methods=["POST"])
@limiter.limit("20 per hour")
@jwt_required()
def remove_product(product_id):
    admin_id = int(get_jwt_identity())

    data = request.get_json() or {}
    reason = data.get("reason", "").strip()
    if not reason:
        return jsonify({"success": False, "message": "A reason is required."}), 400

    product = Product.query.get(product_id)
    if not product:
        return jsonify({"success": False, "message": "Product not found."}), 404

    vendor = product.vendor
    if not vendor:
        return jsonify({"success": False, "message": "Vendor not found for this product."}), 404

    # Deactivate the product (hides it from public listings)
    product.is_active = False
    product.deactivated_by = "admin"
    product.edit_deadline  = datetime.utcnow() + timedelta(days=7)

    existing = VendorStrike.query.filter_by(
        vendor_id=vendor.id,
        product_id=product.id
    ).first()
    if existing:
        return jsonify({"success": False, "message": "This product already has a strike."}), 400
    
    # Issue strike
    vendor.strike_count = (vendor.strike_count or 0) + 1
    strike = VendorStrike(
        vendor_id=vendor.id,
        admin_id=admin_id,
        product_id=product.id,
        product_name=product.name,
        reason=reason,
        strike_number=vendor.strike_count
    )
    db.session.add(strike)

    auto_suspended = False
    if vendor.strike_count >= 3 and vendor.is_active:
        vendor.is_active = False
        vendor.suspended_reason = "strikes"
        vendor.suspended_at = datetime.utcnow()
        auto_suspended = True

    db.session.commit()

    # Emails - best effort, don't fail the request if these fail
    send_vendor_strike_email(vendor.email, vendor.name, reason, vendor.strike_count)
    if auto_suspended:
        send_vendor_suspended_email(
            vendor.email, vendor.name,
            reason="Your account reached 3 strikes for policy violations."
        )

    return jsonify({
        "success": True,
        "message": "Product removed and vendor notified.",
        "strike_count": vendor.strike_count,
        "auto_suspended": auto_suspended
    }), 200


# ── UNFLAG VENDOR (reset strikes, reactivate if suspended for strikes) ─────
@admin_auth_bp.route("/vendors/<int:vendor_id>/unflag", methods=["POST"])
@limiter.limit("20 per hour")
@jwt_required()
def unflag_vendor(vendor_id):
    vendor = Vendor.query.get(vendor_id)
    if not vendor:
        return jsonify({"success": False, "message": "Vendor not found."}), 404
    VendorStrike.query.filter_by(vendor_id=vendor_id).delete()
    vendor.strike_count = 0

    if not vendor.is_active:
        vendor.is_active = True
        vendor.suspended_reason = None
        vendor.suspended_at = None

    db.session.commit()
    send_vendor_reactivated_email(vendor.email, vendor.name)
    return jsonify({"success": True, "message": "Vendor unflagged."}), 200


# ── SUSPEND VENDOR (manual admin action) ────────────────────────────────────
@admin_auth_bp.route("/vendors/<int:vendor_id>/suspend", methods=["POST"])
@limiter.limit("20 per hour")
@jwt_required()
def suspend_vendor(vendor_id):
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()

    vendor = Vendor.query.get(vendor_id)
    if not vendor:
        return jsonify({"success": False, "message": "Vendor not found."}), 404

    vendor.is_active = False
    vendor.suspended_reason = "admin_manual"
    vendor.suspended_at = datetime.utcnow()

    db.session.commit()

    send_vendor_suspended_email(vendor.email, vendor.name, reason=reason or None)

    return jsonify({"success": True, "message": "Vendor suspended and notified."}), 200

@admin_auth_bp.route("/products/slug/<string:slug>", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_admin_product_by_slug(slug):
    p = Product.query.filter_by(share_slug=slug).first()
    if not p:
        return jsonify({"success": False, "message": "Product not found."}), 404

    v = Vendor.query.get(p.vendor_id)
    if not v:
        return jsonify({"success": False, "message": "Vendor not found."}), 404

    if not p.admin_reviewed:
        p.admin_reviewed = True
        db.session.commit()

    product_data = p.to_dict()

    vendor_data = {
        "id":            v.id,
        "name":          v.name,
        "profile_photo": v.profile_photo,
        "badge":         v.badge(),
        "city":          v.city,
        "state":         v.state,
    }

    admin_meta = {
        "active":        p.is_active,
        "reviewed":      p.admin_reviewed,
        "clicks":        p.click_count,
        "created_at":    p.created_at.strftime("%d %b %Y"),
        "vendor_plan":         v.subscription_plan,
        "vendor_active":       v.is_active,
        "vendor_strike_count": v.strike_count,
        "vendor_email":        v.email,
        "vendor_mobile":       v.mobile,
    }

    return jsonify({
        "success":   True,
        "product":   product_data,
        "vendor":    vendor_data,
        "admin_meta": admin_meta
    }), 200
    
# ── VENDOR DETAIL (full info + strike history + live products) ─────────────
@admin_auth_bp.route("/vendors/<int:vendor_id>", methods=["GET"])
@limiter.limit("30 per minute")
@jwt_required()
def get_vendor_detail(vendor_id):
    vendor = Vendor.query.get(vendor_id)
    if not vendor:
        return jsonify({"success": False, "message": "Vendor not found."}), 404

    live_products = Product.query.filter_by(
        vendor_id=vendor.id, is_active=True
    ).order_by(Product.created_at.desc()).all()

    strikes = VendorStrike.query.filter_by(
        vendor_id=vendor.id
    ).order_by(VendorStrike.created_at.desc()).all()

    vendor_data = {
        "id": vendor.id,
        "name": vendor.name,
        "email": vendor.email,
        "mobile": vendor.mobile,
        "gst_number": vendor.gst_number,
        "pincode": vendor.pincode,
        "state": vendor.state,
        "city": vendor.city,
        "area": vendor.area,
        "latitude": vendor.latitude,
        "longitude": vendor.longitude,
        "profile_photo": vendor.profile_photo,
        "is_verified": vendor.is_verified,
        "is_active": vendor.is_active,
        "role": vendor.role,
        "strike_count": vendor.strike_count,
        "suspended_at": vendor.suspended_at.strftime("%d %b %Y, %I:%M %p") if vendor.suspended_at else None,
        "suspended_reason": vendor.suspended_reason,
        "subscription_plan": vendor.subscription_plan,
        "effective_plan": vendor.effective_plan_name(),
        "subscription_expires_at": vendor.subscription_expires_at.strftime("%d %b %Y") if vendor.subscription_expires_at else None,
        "is_subscription_active": vendor.is_subscription_active(),
        "badge": vendor.badge(),
        "priority_score": vendor.priority_score(),
        "max_active_posts": vendor.max_active_posts(),  # None = unlimited
        "active_product_count": vendor.active_product_count(),
        "google_linked": vendor.google_id is not None,
        "created_at": vendor.created_at.strftime("%d %b %Y, %I:%M %p"),
        "updated_at": vendor.updated_at.strftime("%d %b %Y, %I:%M %p"),
    }

    products_data = [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "image": p.image1,
            "slug": p.share_slug,
        }
        for p in live_products
    ]

    strikes_data = [
        {
            "id": s.id,
            "product_name": s.product_name,
            "reason": s.reason,
            "strike_number": s.strike_number,
            "created_at": s.created_at.strftime("%d %b %Y, %I:%M %p"),
            "product_deleted": Product.query.get(s.product_id) is None if s.product_id else True,
        }
        for s in strikes
    ]

    return jsonify({
        "success": True,
        "vendor": vendor_data,
        "products": products_data,
        "strikes": strikes_data
    }), 200
    
# ── ADMIN REACTIVATE PRODUCT ─────────────────────────────────────────────────
@admin_auth_bp.route("/products/<int:product_id>/reactivate", methods=["POST"])
@limiter.limit("30 per minute")
@jwt_required()
def reactivate_product(product_id):
    p = Product.query.get(product_id)
    if not p:
        return jsonify({"success": False, "message": "Product not found."}), 404
    p.is_active = True
    p.deactivated_by = None
    p.edit_deadline = None
    p.admin_reviewed = False
    db.session.commit()
    return jsonify({"success": True, "message": "Product reactivated."}), 200


# ── ADMIN EDIT FLAGGED PRODUCT ────────────────────────────────────────────────
@admin_auth_bp.route("/products/<int:product_id>/edit", methods=["PUT"])
@limiter.limit("30 per minute")
@jwt_required()
def admin_edit_product(product_id):
    p = Product.query.get(product_id)
    if not p:
        return jsonify({"success": False, "message": "Product not found."}), 404

    data = request.get_json()

    def to_float_or_none(val):
        if val is None or val == '':
            return None
        try: return float(val)
        except: return None

    if 'name' in data and data['name']:          p.name             = data['name'].strip()
    if 'description' in data:                    p.description      = data['description'] or None
    if 'rent_per_hour' in data:                  p.rent_per_hour    = to_float_or_none(data['rent_per_hour'])
    if 'rent_per_km' in data:                    p.rent_per_km      = to_float_or_none(data['rent_per_km'])
    if 'rent_per_day' in data:                   p.rent_per_day     = to_float_or_none(data['rent_per_day'])
    if 'rent_per_month' in data:                 p.rent_per_month   = to_float_or_none(data['rent_per_month'])
    if 'security_deposit' in data:               p.security_deposit = to_float_or_none(data['security_deposit'])
    if 'category' in data and data['category']:  p.category         = data['category']
    if 'subcategory' in data:                    p.subcategory      = data['subcategory'] or None
    if 'pincode' in data:                        p.pincode          = data['pincode'] or None
    if 'area' in data:                           p.area             = data['area'] or None
    if 'city' in data:                           p.city             = data['city'] or None
    if 'state' in data:                          p.state            = data['state'] or None

    p.is_active      = True
    p.deactivated_by = None
    p.edit_deadline  = None
    p.admin_reviewed = False

    db.session.commit()
    return jsonify({"success": True, "message": "Product updated and live."}), 200


# ── CLEANUP EXPIRED FLAGGED PRODUCTS ─────────────────────────────────────────
@admin_auth_bp.route("/products/cleanup-expired", methods=["POST"])
@limiter.limit("5 per hour")
@jwt_required()
def cleanup_expired_products():
    from utils.s3 import delete_from_s3
    expired = Product.query.filter(
        Product.deactivated_by == "admin",
        Product.edit_deadline < datetime.utcnow()
    ).all()
    count = 0
    for p in expired:
        for url in p.image_urls():
            delete_from_s3(url)
        db.session.delete(p)
        count += 1
    db.session.commit()
    return jsonify({"success": True, "deleted": count}), 200