# OLR India - Public Routes
# No auth required. Used by index page and public product pages.

from flask import Blueprint, jsonify,json
from extensions import db
from models.vendor import Product, Vendor, PRODUCT_CATEGORIES
from extensions import limiter
from flask import Blueprint, jsonify, request, redirect
from extensions import cache

public_bp = Blueprint("public", __name__)


# ── All active public products (index page) ───────────────────
@public_bp.route("/public", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_products():
    from sqlalchemy import case

    page       = request.args.get("page", 1, type=int)
    per_page   = min(request.args.get("per_page", 20, type=int), 50)
    category   = request.args.get("category", "").strip()
    city       = request.args.get("city", "").strip().lower()
    price_type = request.args.get("price_type", "day").strip()
    price_min  = request.args.get("price_min", 0, type=float)
    price_max  = request.args.get("price_max", None, type=float)
    search     = request.args.get("search", "").strip().lower()
    cache_key = f"public:{page}:{per_page}:{category}:{city}:{price_type}:{price_min}:{price_max}:{search}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(json.loads(cached)), 200
    query = (
        db.session.query(Product, Vendor)
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(
            Product.is_active  == True,
            Vendor.is_active   == True,
            Vendor.is_verified == True,
        )
    )

    if category:
        query = query.filter(Product.category == category)
    if city:
        query = query.filter(
            db.or_(
                Product.city.ilike(f"%{city}%"),
                Product.area.ilike(f"%{city}%"),
                Product.state.ilike(f"%{city}%"),
            )
        )
    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f"%{search}%"),
                Product.description.ilike(f"%{search}%"),
                Product.category.ilike(f"%{search}%"),
            )
        )
    if price_min > 0 or price_max is not None:
        price_col = {"hour": Product.rent_per_hour, "km": Product.rent_per_km, "day": Product.rent_per_day, "month": Product.rent_per_month}.get(price_type, Product.rent_per_day)
        if price_min > 0:
            query = query.filter(price_col >= price_min)
        if price_max is not None:
            query = query.filter(price_col <= price_max)

    plan_order = case(
        (Vendor.subscription_plan == "premium", 0),
        (Vendor.subscription_plan == "growth",  1),
        (Vendor.subscription_plan == "starter", 2),
        else_=3
    )
    query  = query.order_by(plan_order, Product.click_count.desc())
    total  = query.count()
    rows   = query.offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for p, v in rows:
        d = p.to_dict(include_vendor_badge=True)
        d["vendor_plan"] = v.effective_plan_name()
        d["vendor_city"] = v.city
        result.append(d)

    response_data = {
        "success": True, "products": result,
        "page": page, "per_page": per_page,
        "total": total, "has_more": (page * per_page) < total,
    }
    cache.setex(cache_key, 60, json.dumps(response_data))
    return jsonify(response_data), 200


# ── Single product by share_slug (public product page /p/<slug>) ─
@public_bp.route("/public/<string:slug>", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_product(slug):
    p = Product.query.filter_by(share_slug=slug, is_active=True).first()
    if not p:
        return jsonify({"success": False, "message": "Product not found or no longer available."}), 404

    v = Vendor.query.get(p.vendor_id)
    if not v or not v.is_active or not v.is_verified:
        return jsonify({"success": False, "message": "This listing is not available."}), 404

    product_data = p.to_dict()

    # Vendor info - no phone/email exposed
    vendor_data = {
        "id":            v.id,
        "name":          v.name,
        "profile_photo": v.profile_photo,
        "badge":         v.badge(),
        "city":          v.city,
        "state":         v.state,
    }

    return jsonify({
        "success": True,
        "product": product_data,
        "vendor":  vendor_data
    }), 200
    

# ── Known social-media crawler user-agents ─────────────────────
CRAWLER_UA_SUBSTRINGS = [
    "whatsapp", "facebookexternalhit", "twitterbot", "linkedinbot",
    "slackbot", "telegrambot", "discordbot", "pinterest", "skypeuripreview",
]

def is_crawler(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(bot in ua for bot in CRAWLER_UA_SUBSTRINGS)

@public_bp.route('/.well-known/assetlinks.json', methods=["GET"])
def assetlinks():
    data = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": "com.example.olr_india",
            "sha256_cert_fingerprints": [
                "CB:90:41:16:37:05:4C:89:1A:9D:30:3C:89:EF:FC:27:C2:C1:53:06:9D:85:EE:1C:A1:1C:CD:6E:00:65:8B:A6"
            ]
        }
    }]
    return jsonify(data)