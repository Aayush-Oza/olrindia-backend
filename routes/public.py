# backend/routes/public.py
# OLR India - Public Routes
# No auth required. Used by index page and public product pages.

from flask import Blueprint, jsonify, json, request, redirect
from extensions import db, limiter, cache
from models.vendor import Product, Vendor, PRODUCT_CATEGORIES

public_bp = Blueprint("public", __name__)

# ── Change this to your actual domain ─────────────────────────────────────────
BASE_URL = "https://olrindia.com"

# ── Exact filenames as they exist in  backend/static/categories/ ──────────────
# Key   = category name (must match PRODUCT_CATEGORIES in models/vendor.py)
# Value = filename inside static/categories/
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
    'Electrical & Power Tools':           'ProfessionalConstructionToolsDisplay.webp',            # no dedicated file, reuse
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


# ── /api/products/categories ──────────────────────────────────────────────────
@public_bp.route("/categories", methods=["GET"])
@limiter.limit("60 per minute")
def get_categories():
    """
    Returns only categories that have at least 1 active product.
    Each item includes image_url served from this server's /static/categories/.
    Flutter & web render the image from this URL — no assets bundled in app.
    To change a category image: just replace the .webp file on server. Done.
    """
    from sqlalchemy import func

    # One query — count active products per category
    counts = (
        db.session.query(Product.category, func.count(Product.id))
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(
            Product.is_active  == True,
            Vendor.is_active   == True,
            Vendor.is_verified == True,
        )
        .group_by(Product.category)
        .all()
    )
    count_map = {cat: cnt for cat, cnt in counts}

    categories = []
    for cat in PRODUCT_CATEGORIES.keys():
        cnt = count_map.get(cat, 0)
        if cnt == 0:
            continue  # hide empty categories from slider

        filename  = CATEGORY_IMAGES.get(cat)
        # URL-encode spaces so the link works in browsers & Flutter
        if filename:
            from urllib.parse import quote
            image_url = f"{BASE_URL}/static/categories/{quote(filename)}"
        else:
            image_url = None

        categories.append({
            'name':          cat,
            'emoji':         CATEGORY_EMOJIS.get(cat, '📦'),
            'image_url':     image_url,
            'product_count': cnt,
        })

    return jsonify({"success": True, "categories": categories}), 200


# ── /api/products/public  (index page + Flutter home) ─────────────────────────
@public_bp.route("/public", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_products():
    from sqlalchemy import case

    page       = request.args.get("page",      1,    type=int)
    per_page   = min(request.args.get("per_page", 20, type=int), 50)
    category   = request.args.get("category",  "").strip()
    city       = request.args.get("city",       "").strip().lower()
    price_type = request.args.get("price_type", "").strip()
    price_min  = request.args.get("price_min",  0,    type=float)
    price_max  = request.args.get("price_max",  None, type=float)
    search     = request.args.get("search",     "").strip().lower()

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
        conditions = []
        for col in price_col_map.values():
            col_filter = col.isnot(None)
            if price_min > 0:
                col_filter = db.and_(col_filter, col >= price_min)
            if price_max is not None:
                col_filter = db.and_(col_filter, col <= price_max)
            conditions.append(col_filter)
        query = query.filter(db.or_(*conditions))

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
        "success":  True,
        "products": result,
        "page":     page,
        "per_page": per_page,
        "total":    total,
        "has_more": (page * per_page) < total,
    }
    cache.setex(cache_key, 60, json.dumps(response_data))
    return jsonify(response_data), 200


# ── /api/products/public/<slug> ───────────────────────────────────────────────
@public_bp.route("/public/<string:slug>", methods=["GET"])
@limiter.limit("60 per minute")
def get_public_product(slug):
    p = Product.query.filter_by(share_slug=slug, is_active=True).first()
    if not p:
        return jsonify({"success": False, "message": "Product not found or no longer available."}), 404

    v = Vendor.query.get(p.vendor_id)
    if not v or not v.is_active or not v.is_verified:
        return jsonify({"success": False, "message": "This listing is not available."}), 404

    vendor_data = {
        "id":            v.id,
        "name":          v.name,
        "profile_photo": v.profile_photo,
        "badge":         v.badge(),
        "city":          v.city,
        "state":         v.state,
    }
    return jsonify({"success": True, "product": p.to_dict(), "vendor": vendor_data}), 200

# ── Known social-media crawler user-agents ────────────────────────────────────
CRAWLER_UA_SUBSTRINGS = [
    "whatsapp", "facebookexternalhit", "twitterbot", "linkedinbot",
    "slackbot", "telegrambot", "discordbot", "pinterest", "skypeuripreview",
]

def is_crawler(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(bot in ua for bot in CRAWLER_UA_SUBSTRINGS)