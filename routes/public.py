# backend/routes/public.py
import math
from datetime import datetime
from flask import Blueprint, jsonify, json, request, redirect
from extensions import db, limiter, cache
from models.vendor import Product, Vendor, PRODUCT_CATEGORIES

public_bp = Blueprint("public", __name__)

BASE_URL = "https://olrindia.com"

CATEGORY_ICONS = {
    'Construction Equipment':             'noto:building-construction',
    'Furniture & Home Appliances':        'noto:couch-and-lamp',
    'Photography & Content Creator Gear': 'noto:camera',
    'Events & Weddings':                  'noto:party-popper',
    'Fashion & Designer Wear':            'noto:dress',
    'Agricultural Equipment':             'noto:tractor',
    'Passenger Vehicles':                 'noto:automobile',
    'Bikes & Scooters':                   'noto:motor-scooter',
    'Medical Equipment':                  'noto:stethoscope',
    'Baby & Kids Gear':                   'noto:baby',
    'Adventure & Trekking Gear':          'noto:camping',
    'Sports & Fitness Equipment':         'noto:person-lifting-weights',
    'Electrical & Power Tools':           'noto:electric-plug',
    'Commercial Vehicles':                'noto:delivery-truck',
    'Tools & Tackles':                    'noto:hammer-and-wrench',
    'Properties':                         'noto:house',
    'Industrial Equipment':               'noto:gear',
    'Warehouse & Storage':                'noto:warehouse',
    'Cargo & Shipping':                   'noto:package',
    'Machineries':                        'noto:wrench',
    'Musical Instruments':                'noto:guitar',
    'Office and Business Essentials':     'noto:briefcase',
}

# ── Plan rank map (higher = better plan) ─────────────────────────────────────
PLAN_RANK = {
    "premium":        3,
    "premium_yearly": 3,
    "growth":         2,
    "growth_yearly":  2,
    "starter":        1,
    "starter_yearly": 1,
    "free":           0,
}


# ── Haversine distance (km) ───────────────────────────────────────────────────
def haversine_km(lat1, lng1, lat2, lng2):
    """Returns distance in km between two lat/lng points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Clear all public cache keys ───────────────────────────────────────────────
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
        cache.delete("categories:all")
    except Exception:
        pass


# ── Plan active filter ────────────────────────────────────────────────────────
def vendor_plan_active_filter():
    return db.or_(
        Vendor.subscription_plan == "free",
        Vendor.subscription_expires_at > datetime.utcnow()
    )


# ── /products/categories ──────────────────────────────────────────────────────
@public_bp.route("/categories", methods=["GET"])
@limiter.limit("60 per minute")
def get_categories():
    listing_type = request.args.get("listing_type", "all").strip().lower()
    if listing_type not in ("rent", "sell", "all"):
        listing_type = "all"

    cache_key = f"categories:{listing_type}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(json.loads(cached)), 200

    from sqlalchemy import func

    base_query = (
        db.session.query(Product.category, func.count(Product.id))
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(
            Product.is_active      == True,
            Vendor.is_active       == True,
            Vendor.is_verified     == True,
            vendor_plan_active_filter(),
            # Only count products that have proper coordinates
            Product.latitude.isnot(None),
            Product.longitude.isnot(None),
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
        categories.append({
            'name':          cat,
            'icon':          CATEGORY_ICONS.get(cat, 'noto:package'),
            'product_count': cnt,
        })

    response_data = {"success": True, "categories": categories, "listing_type": listing_type}
    cache.setex(cache_key, 300, json.dumps(response_data))
    return jsonify(response_data), 200


# ── /products/public ──────────────────────────────────────────────────────────
# Sort logic (Option B):
#   WITH user lat/lng  → plan tier first (premium→growth→starter→free),
#                         within each tier sorted by nearest distance
#   WITHOUT user lat/lng → plan tier first, then click_count desc (original)
#
# Only products WITH latitude+longitude are shown publicly.
@public_bp.route("/public", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_products():
    page         = request.args.get("page",         1,     type=int)
    per_page     = min(request.args.get("per_page", 20,    type=int), 50)
    category     = request.args.get("category",     "").strip()
    city         = request.args.get("city",         "").strip()
    search       = request.args.get("search",       "").strip().lower()
    listing_type = request.args.get("listing_type", "all").strip().lower()

    # User location (from browser GPS)
    user_lat_raw = request.args.get("user_lat", "").strip()
    user_lng_raw = request.args.get("user_lng", "").strip()
    try:
        user_lat = float(user_lat_raw) if user_lat_raw else None
        user_lng = float(user_lng_raw) if user_lng_raw else None
    except ValueError:
        user_lat = user_lng = None

    has_user_location = user_lat is not None and user_lng is not None

    # rent-specific filters
    price_type = request.args.get("price_type", "").strip()
    price_min  = request.args.get("price_min",  0,    type=float)
    price_max  = request.args.get("price_max",  None, type=float)

    # sell-specific filters
    condition = request.args.get("condition", "").strip()

    if listing_type not in ("rent", "sell", "all"):
        listing_type = "all"

    # Distance-based sorting cannot be cached meaningfully per user,
    # so we only cache when no user location is provided.
    cache_key = None
    if not has_user_location:
        cache_key = (
            f"public:{listing_type}:{page}:{per_page}:{category}:{city}:"
            f"{price_type}:{price_min}:{price_max}:{search}:{condition}"
        )
        cached = cache.get(cache_key)
        if cached:
            return jsonify(json.loads(cached)), 200

    # ── Base filters ──────────────────────────────────────────────────────────
    base_filters = [
        Product.is_active      == True,
        Vendor.is_active       == True,
        Vendor.is_verified     == True,
        vendor_plan_active_filter(),
        # Only show products with proper GPS coordinates
        Product.latitude.isnot(None),
        Product.longitude.isnot(None),
    ]

    if listing_type in ("rent", "sell"):
        base_filters.append(Product.listing_type == listing_type)

    query = (
        db.session.query(Product, Vendor)
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(*base_filters)
    )

    # ── Common filters ────────────────────────────────────────────────────────
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

    # ── Rent-specific price filters ───────────────────────────────────────────
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

    # ── Sell-specific filters ─────────────────────────────────────────────────
    elif listing_type == "sell":
        if price_min > 0:
            query = query.filter(Product.selling_price >= price_min)
        if price_max is not None:
            query = query.filter(Product.selling_price <= price_max)
        if condition:
            query = query.filter(Product.condition == condition)

    # ── Fetch all matching rows (needed for distance sort in Python) ──────────
    if has_user_location:
        # Fetch all matching rows, sort in Python by (plan_rank DESC, distance ASC)
        all_rows = query.all()

        def sort_key(row):
            p, v = row
            plan_rank = PLAN_RANK.get(v.effective_plan_name(), 0)
            distance  = haversine_km(user_lat, user_lng, float(p.latitude), float(p.longitude))
            # Negate plan_rank so higher plan = smaller sort value (sorts first)
            return (-plan_rank, distance)

        all_rows.sort(key=sort_key)

        total    = len(all_rows)
        offset   = (page - 1) * per_page
        page_rows = all_rows[offset: offset + per_page]

        result = []
        for p, v in page_rows:
            d = p.to_dict(include_vendor_badge=True)
            d["vendor_plan"] = v.effective_plan_name()
            d["vendor_city"] = v.city
            d["distance_km"] = round(
                haversine_km(user_lat, user_lng, float(p.latitude), float(p.longitude)), 1
            )
            result.append(d)

    else:
        # No user location - original DB-level sort: plan tier then clicks
        from sqlalchemy import case
        plan_order = case(
            (Vendor.subscription_plan.in_(["premium", "premium_yearly"]), 0),
            (Vendor.subscription_plan.in_(["growth",  "growth_yearly"]),  1),
            (Vendor.subscription_plan.in_(["starter", "starter_yearly"]), 2),
            else_=3
        )
        query = query.order_by(plan_order, Product.click_count.desc(), Product.id.desc())

        total     = query.count()
        page_rows = query.offset((page - 1) * per_page).limit(per_page).all()

        result = []
        for p, v in page_rows:
            d = p.to_dict(include_vendor_badge=True)
            d["vendor_plan"] = v.effective_plan_name()
            d["vendor_city"] = v.city
            result.append(d)

    response_data = {
        "success":            True,
        "products":           result,
        "listing_type":       listing_type,
        "page":               page,
        "per_page":           per_page,
        "total":              total,
        "has_more":           (page * per_page) < total,
        "location_used":      has_user_location,
    }

    # Only cache when no user location (distance results are per-user)
    if cache_key:
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

    # Product must have coordinates
    if p.latitude is None or p.longitude is None:
        return jsonify({"success": False, "message": "This listing is not available."}), 404

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
        "store_slug":    v.store_slug,
    }
    response_data = {"success": True, "product": p.to_dict(), "vendor": vendor_data}
    cache.setex(cache_key, 120, json.dumps(response_data))
    return jsonify(response_data), 200


# ── /vendor/<store_slug> ──────────────────────────────────────────────────────
@public_bp.route("/vendor/<string:store_slug>", methods=["GET"])
@limiter.limit("60 per minute")
def get_vendor_store(store_slug):
    listing_type = request.args.get("listing_type", "all").strip().lower()
    if listing_type not in ("rent", "sell", "all"):
        listing_type = "all"

    page     = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 50)

    cache_key = f"vendor_store:{store_slug}:{listing_type}:{page}:{per_page}"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(json.loads(cached)), 200

    v = Vendor.query.filter_by(store_slug=store_slug, is_active=True, is_verified=True).first()
    if not v:
        return jsonify({"success": False, "message": "Vendor store not found."}), 404

    plan_ok = (
        v.subscription_plan == "free" or
        (v.subscription_expires_at and v.subscription_expires_at > datetime.utcnow())
    )
    if not plan_ok:
        return jsonify({"success": False, "message": "This store is not available."}), 404

    # Total active listings with coordinates
    total_listings = Product.query.filter_by(
        vendor_id=v.id, is_active=True
    ).filter(
        Product.latitude.isnot(None),
        Product.longitude.isnot(None),
    ).count()

    search = request.args.get("search", "").strip().lower()

    query = Product.query.filter_by(vendor_id=v.id, is_active=True).filter(
        Product.latitude.isnot(None),
        Product.longitude.isnot(None),
    )
    if listing_type in ("rent", "sell"):
        query = query.filter_by(listing_type=listing_type)
    if search:
        query = query.filter(db.or_(
            Product.name.ilike(f"%{search}%"),
            Product.description.ilike(f"%{search}%"),
            Product.category.ilike(f"%{search}%"),
        ))
    query = query.order_by(Product.click_count.desc())

    total    = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    vendor_data = {
        "id":             v.id,
        "name":           v.name or '',
        "profile_photo":  v.profile_photo,
        "badge":          v.badge(),
        "city":           v.city,
        "state":          v.state,
        "store_slug":     v.store_slug,
        "member_since":   v.created_at.strftime("%B %Y"),
        "total_listings": total_listings,
    }

    response_data = {
        "success":      True,
        "vendor":       vendor_data,
        "products":     [p.to_dict(include_vendor_badge=True) for p in products],
        "page":         page,
        "per_page":     per_page,
        "total":        total,
        "has_more":     (page * per_page) < total,
        "listing_type": listing_type,
    }
    cache.setex(cache_key, 60, json.dumps(response_data))
    return jsonify(response_data), 200


CRAWLER_UA_SUBSTRINGS = [
    "whatsapp", "facebookexternalhit", "twitterbot", "linkedinbot",
    "slackbot", "telegrambot", "discordbot", "pinterest", "skypeuripreview",
]

def is_crawler(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(bot in ua for bot in CRAWLER_UA_SUBSTRINGS)