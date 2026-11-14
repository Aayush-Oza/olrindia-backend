# backend/routes/public.py
from datetime import datetime
from flask import Blueprint, jsonify, json, request, redirect
from extensions import db, limiter, cache
from models.vendor import Product, Vendor, PRODUCT_CATEGORIES

public_bp = Blueprint("public", __name__)

BASE_URL = "https://olrindia.com"

CATEGORY_IMAGES = {
    'Construction Equipment':             'SunriseMachineryattheConstruction Site.webp',
    'Furniture & Home Appliances':        'ModernShowroomLivingSpace.webp',
    'Photography & Content Creator Gear': 'PhotographyContentCreatorGear.webp',
    'Events & Weddings':                  'EventsWeddings.webp',
    'Fashion & Designer Wear':            'FashionDesignerWear.webp',
    'Agricultural Equipment':             'AgriculturalEquipment.webp',
    'Passenger Vehicles':                 'PassengerVehicles.webp',
    'Bikes & Scooters':                   'BikesScooters.webp',
    'Medical Equipment':                  'MedicalEquipment.webp',
    'Baby & Kids Gear':                   'BabyKidsGear.webp',
    'Adventure & Trekking Gear':          'AdventureTrekkingGear.webp',
    'Sports & Fitness Equipment':         'SportsFitnessEquipment.webp',
    'Electrical & Power Tools':           'ProfessionalConstructionToolsDisplay.webp',
    'Commercial Vehicles':                'CommercialVehicles.webp',
    'Tools & Tackles':                    'ToolsTackles.webp',
    'Properties':                         'Properties.webp',
    'Industrial Equipment':               'IndustrialEquipment.webp',
    'Warehouse & Storage':                'WarehouseStorage.webp',
    'Cargo & Shipping':                   'CargoShipping.webp',
    'Machineries':                        'Machineries.webp',
    'Musical Instruments':                'Musical Instruments.webp',
    'Office and Business Essentials':     'ModernOfficeEssentialsShowroom.webp',
}

CATEGORY_EMOJIS = {
    'Construction Equipment':             '🏗️',
    'Furniture & Home Appliances':        '🛋️',
    'Photography & Content Creator Gear': '📷',
    'Events & Weddings':                  '🎉',
    'Fashion & Designer Wear':            '👗',
    'Agricultural Equipment':             '🌾',
    'Passenger Vehicles':                 '🚗',
    'Bikes & Scooters':                   '🏍️',
    'Medical Equipment':                  '🩺',
    'Baby & Kids Gear':                   '🍼',
    'Adventure & Trekking Gear':          '⛺',
    'Sports & Fitness Equipment':         '🏋️',
    'Electrical & Power Tools':           '⚡',
    'Commercial Vehicles':                '🚛',
    'Tools & Tackles':                    '🛠️',
    'Properties':                         '🏢',
    'Industrial Equipment':               '⚙️',
    'Warehouse & Storage':                '🏭',
    'Cargo & Shipping':                   '📦',
    'Machineries':                        '🔧',
    'Musical Instruments':                '🎸',
    'Office and Business Essentials':     '💼',
}


# ── helper: clear all public cache keys ──────────────────────────────────────
def clear_public_cache():
    """Call this whenever a product or vendor changes."""
    try:
        keys = cache.keys("public:*")
        if keys:
            cache.delete(*keys)
        product_keys = cache.keys("product:*")
        if product_keys:
            cache.delete(*product_keys)
        cache.delete("categories")
        cache.delete("categories:rent")
        cache.delete("categories:sell")
    except Exception:
        pass


# ── helper: plan is active filter ────────────────────────────────────────────
def vendor_plan_active_filter():
    """
    Ensures vendor's plan is either free (no expiry needed) or a paid plan
    that hasn't expired yet. Used in all public listing queries.
    """
    return db.or_(
        Vendor.subscription_plan == "free",
        Vendor.subscription_expires_at > datetime.utcnow()
    )


# ── /products/categories ──────────────────────────────────────────────────────
# Returns categories with product counts, filtered by listing_type.
# listing_type param: "rent" (default) | "sell" | "all"
@public_bp.route("/categories", methods=["GET"])
@limiter.limit("60 per minute")
def get_categories():
    listing_type = request.args.get("listing_type", "rent").strip().lower()
    if listing_type not in ("rent", "sell", "all"):
        listing_type = "rent"

    cache_key = f"categories:{listing_type}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(json.loads(cached)), 200

    from sqlalchemy import func
    from urllib.parse import quote

    base_query = (
        db.session.query(Product.category, func.count(Product.id))
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(
            Product.is_active  == True,
            Vendor.is_active   == True,
            Vendor.is_verified == True,
            vendor_plan_active_filter(),
        )
    )

    if listing_type in ("rent", "sell"):
        base_query = base_query.filter(Product.listing_type == listing_type)

    counts    = base_query.group_by(Product.category).all()
    count_map = {cat: cnt for cat, cnt in counts}

    categories = []
    for cat in PRODUCT_CATEGORIES.keys():
        cnt = count_map.get(cat, 0)
        if cnt == 0:
            continue
        filename  = CATEGORY_IMAGES.get(cat)
        image_url = f"{BASE_URL}/assets/categories/{quote(filename)}" if filename else None
        categories.append({
            'name':          cat,
            'emoji':         CATEGORY_EMOJIS.get(cat, '📦'),
            'image_url':     image_url,
            'product_count': cnt,
        })

    response_data = {"success": True, "categories": categories, "listing_type": listing_type}
    cache.setex(cache_key, 300, json.dumps(response_data))
    return jsonify(response_data), 200


# ── /products/public ──────────────────────────────────────────────────────────
# listing_type param: "rent" (default) | "sell"
# Price filters only apply to rent listings; sell listings use price_min/price_max
# against selling_price instead.
@public_bp.route("/public", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_products():
    from sqlalchemy import case

    page         = request.args.get("page",         1,     type=int)
    per_page     = min(request.args.get("per_page", 20,    type=int), 50)
    category     = request.args.get("category",     "").strip()
    city         = request.args.get("city",         "").strip()
    search       = request.args.get("search",       "").strip().lower()
    listing_type = request.args.get("listing_type", "rent").strip().lower()

    # rent-specific filters
    price_type = request.args.get("price_type", "").strip()
    price_min  = request.args.get("price_min",  0,    type=float)
    price_max  = request.args.get("price_max",  None, type=float)

    # sell-specific filters
    condition  = request.args.get("condition",  "").strip()

    if listing_type not in ("rent", "sell"):
        listing_type = "rent"

    cache_key = (
        f"public:{listing_type}:{page}:{per_page}:{category}:{city}:"
        f"{price_type}:{price_min}:{price_max}:{search}:{condition}"
    )
    cached = cache.get(cache_key)
    if cached:
        return jsonify(json.loads(cached)), 200

    query = (
        db.session.query(Product, Vendor)
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(
            Product.is_active    == True,
            Product.listing_type == listing_type,
            Vendor.is_active     == True,
            Vendor.is_verified   == True,
            vendor_plan_active_filter(),
        )
    )

    if category:
        query = query.filter(Product.category == category)

    if city:
        parts      = [p.strip() for p in city.split(',') if p.strip()]
        conditions = []
        for part in parts:
            conditions.append(Product.area.ilike(f"%{part}%"))
            conditions.append(Product.city.ilike(f"%{part}%"))
            conditions.append(Product.state.ilike(f"%{part}%"))
        query = query.filter(db.or_(*conditions))

    if search:
        query = query.filter(db.or_(
            Product.name.ilike(f"%{search}%"),
            Product.description.ilike(f"%{search}%"),
            Product.category.ilike(f"%{search}%"),
        ))

    # ── rent price filters ────────────────────────────────────────────────────
    if listing_type == "rent":
        price_col_map = {
            "hour":  Product.rent_per_hour,
            "km":    Product.rent_per_km,
            "day":   Product.rent_per_day,
            "month": Product.rent_per_month,
        }
        if price_type and price_type in price_col_map:
            price_col = price_col_map[price_type]
            query = query.filter(price_col.isnot(None))
            if price_min > 0:
                query = query.filter(price_col >= price_min)
            if price_max is not None:
                query = query.filter(price_col <= price_max)
        elif price_min > 0 or price_max is not None:
            conds = []
            for col in price_col_map.values():
                col_filter = col.isnot(None)
                if price_min > 0:
                    col_filter = db.and_(col_filter, col >= price_min)
                if price_max is not None:
                    col_filter = db.and_(col_filter, col <= price_max)
                conds.append(col_filter)
            query = query.filter(db.or_(*conds))

    # ── sell price + condition filters ────────────────────────────────────────
    elif listing_type == "sell":
        query = query.filter(Product.selling_price.isnot(None))
        if price_min > 0:
            query = query.filter(Product.selling_price >= price_min)
        if price_max is not None:
            query = query.filter(Product.selling_price <= price_max)
        if condition:
            query = query.filter(Product.condition == condition)

    # ── ordering: premium > growth > starter > free, then by clicks ──────────
    plan_order = case(
        (Vendor.subscription_plan == "premium", 0),
        (Vendor.subscription_plan == "growth",  1),
        (Vendor.subscription_plan == "starter", 2),
        else_=3
    )
    query = query.order_by(plan_order, Product.click_count.desc())

    total = query.count()
    rows  = query.offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for p, v in rows:
        d = p.to_dict(include_vendor_badge=True)
        d["vendor_plan"] = v.effective_plan_name()
        d["vendor_city"] = v.city
        result.append(d)

    response_data = {
        "success":      True,
        "products":     result,
        "listing_type": listing_type,
        "page":         page,
        "per_page":     per_page,
        "total":        total,
        "has_more":     (page * per_page) < total,
    }
    cache.setex(cache_key, 60, json.dumps(response_data))
    return jsonify(response_data), 200


# ── /products/public/<slug> ───────────────────────────────────────────────────
@public_bp.route("/public/<string:slug>", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_product(slug):
    cache_key = f"product:{slug}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(json.loads(cached)), 200

    p = Product.query.filter_by(share_slug=slug, is_active=True).first()
    if not p:
        return jsonify({"success": False, "message": "Product not found or no longer available."}), 404

    v = Vendor.query.get(p.vendor_id)
    if not v or not v.is_active or not v.is_verified:
        return jsonify({"success": False, "message": "This listing is not available."}), 404

    plan_ok = (
        v.subscription_plan == "free" or
        (v.subscription_expires_at and v.subscription_expires_at > datetime.utcnow())
    )
    if not plan_ok:
        return jsonify({"success": False, "message": "This listing is not available."}), 404

    vendor_data = {
        "id":            v.id,
        "name":          v.name or '',
        "profile_photo": v.profile_photo,
        "badge":         v.badge(),
        "city":          v.city,
        "state":         v.state,
    }
    # to_dict() already includes listing_type, selling_price, condition
    response_data = {"success": True, "product": p.to_dict(), "vendor": vendor_data}
    cache.setex(cache_key, 120, json.dumps(response_data))
    return jsonify(response_data), 200


CRAWLER_UA_SUBSTRINGS = [
    "whatsapp", "facebookexternalhit", "twitterbot", "linkedinbot",
    "slackbot", "telegrambot", "discordbot", "pinterest", "skypeuripreview",
]

def is_crawler(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(bot in ua for bot in CRAWLER_UA_SUBSTRINGS)