# OLR India - Vendor Model
# Represents the vendors table in MySQL
# Vendors = businesses/individuals who list products for rent

import secrets
from datetime import datetime, timedelta
from extensions import db


# ── PLAN CONFIG ────────────────────────────────────────────────────────────
# Single source of truth for plan limits + ranking weight + badge.
# priority_score: used to sort listings (higher = shown first)
# badge: shown next to vendor/product on frontend ("verified" = blue tick style,
#        "featured" = gold/star style). None = no badge.
PLAN_LIMITS = {
    "free":    {"max_active_posts": 5,    "priority_score": 0, "badge": None,
                "label": "Free",          "price": 0},
    "starter": {"max_active_posts": 10,   "priority_score": 1, "badge": None,
                "label": "Starter",       "price": 249},
    "growth":  {"max_active_posts": 20,   "priority_score": 2, "badge": "verified",
                "label": "Growth",        "price": 449},
    "premium": {"max_active_posts": None, "priority_score": 3, "badge": "featured",
                "label": "Premium",       "price": 999},
}

class Vendor(db.Model):
    __tablename__ = "vendors"

    # ── Primary Key ───────────────────────────────────────────────────────────
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # ── Basic Info ────────────────────────────────────────────────────────────
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    mobile = db.Column(db.String(15), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)

    # ── Business Tax ──────────────────────────────────────────────────────────
    gst_number = db.Column(db.String(15), nullable=True)

    # ── Location ──────────────────────────────────────────────────────────────
    pincode = db.Column(db.String(6), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    area = db.Column(db.String(200), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    # ── Profile ───────────────────────────────────────────────────────────────
    profile_photo = db.Column(db.String(500), nullable=True)  # S3 URL

    # ── Account Status ────────────────────────────────────────────────────────
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), default="vendor")

    # ── Moderation / Strikes ──────────────────────────────────────────────────
    # Incremented each time admin removes one of this vendor's products for
    # a policy violation. At 3, vendor is auto-suspended (is_active=False)
    # and locked to read-only dashboard until admin manually reactivates.
    strike_count = db.Column(db.Integer, default=0, nullable=False)
    suspended_at = db.Column(db.DateTime, nullable=True)
    suspended_reason = db.Column(db.String(50), nullable=True)  # e.g. "strikes"

    # ── Subscription ──────────────────────────────────────────────────────────
    # starter / growth / premium = paid tiers, see PLAN_LIMITS above
    subscription_plan = db.Column(
        db.Enum("free", "starter", "growth", "premium"),
        default="free",
        nullable=False
    )
    # For paid plans: when the current billing cycle ends.
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    pending_plan = db.Column(db.String(20), nullable=True)
    # ── Social Login ──────────────────────────────────────────────────────────
    google_id = db.Column(db.String(200), unique=True, nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Plan helpers ─────────────────────────────────────────────────────────
    def plan_config(self):
        """Returns the PLAN_LIMITS dict for this vendor's current effective plan.
        If a paid/trial plan has expired, treat as 'free' until renewed."""
        plan = self.subscription_plan or "free"
        if plan in ("starter", "growth", "premium"):
            if self.subscription_expires_at is None or datetime.utcnow() > self.subscription_expires_at:
                plan = "free"
        return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])

    def effective_plan_name(self):
        plan = self.subscription_plan or "free"
        if plan in ("starter", "growth", "premium"):
            if self.subscription_expires_at is None or datetime.utcnow() > self.subscription_expires_at:
                return "free"
        return plan

    def is_subscription_active(self):
        """True only for a currently-paid (non-trial, non-free) active plan."""
        if self.subscription_plan not in ("starter", "growth", "premium"):
            return False
        if self.subscription_expires_at is None:
            return False
        return datetime.utcnow() < self.subscription_expires_at

    def badge(self):
        """Returns 'verified', 'featured', or None - based on effective plan."""
        return self.plan_config()["badge"]

    def has_verified_badge(self):
        return self.badge() is not None
    
    def is_suspended_for_strikes(self):
        return not self.is_active and self.suspended_reason in ("strikes", "admin_manual")

    def priority_score(self):
        """Used to sort product listings - higher shows first."""
        return self.plan_config()["priority_score"]

    def max_active_posts(self):
        return self.plan_config()["max_active_posts"]
    def days_until_expiry(self):
        if self.subscription_plan == "free":
            return None
        if not self.subscription_expires_at:
            return None
        delta = self.subscription_expires_at - datetime.utcnow()
        return max(0, delta.days)

    def should_show_expiry_banner(self):
        days = self.days_until_expiry()
        if days is None:
            return False
        return days <= 5

    def active_product_count(self):
        return Product.query.filter_by(vendor_id=self.id, is_active=True).count()

    def can_add_product(self):
        limit = self.max_active_posts()
        if limit is None:
            return True, None
        current = self.active_product_count()
        if current >= limit:
            return False, (
                f"You've reached your plan's limit of {limit} active posts. "
                f"Upgrade your plan to list more."
            )
        return True, None

class VendorVerificationToken(db.Model):
    """Magic link tokens for vendor email verification"""
    __tablename__ = "vendor_verification_tokens"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vendor = db.relationship("Vendor", backref="verification_tokens")

    @staticmethod
    def generate(vendor_id):
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        return VendorVerificationToken(
            vendor_id=vendor_id,
            token=token,
            expires_at=expires_at
        )

    def is_valid(self):
        return (
            not self.is_used and
            datetime.utcnow() < self.expires_at
        )


class VendorPasswordResetToken(db.Model):
    """Password reset link tokens for vendors"""
    __tablename__ = "vendor_password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vendor = db.relationship("Vendor", backref="password_reset_tokens")

    @staticmethod
    def generate(vendor_id):
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        return VendorPasswordResetToken(
            vendor_id=vendor_id,
            token=token,
            expires_at=expires_at
        )

    def is_valid(self):
        return (
            not self.is_used and
            datetime.utcnow() < self.expires_at
        )


class Product(db.Model):
    __tablename__ = "products"

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    vendor_id        = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    category = db.Column(db.Enum(
        "Construction Equipment",
        "Furniture & Home Appliances",
        "Photography & Content Creator Gear",
        "Events & Weddings",
        "Fashion & Designer Wear",
        "Agricultural Equipment",
        "Passenger Vehicles",
        "Bikes & Scooters",
        "Medical Equipment",
        "Baby & Kids Gear",
        "Adventure & Trekking Gear",
        "Sports & Fitness Equipment",
        "Electrical & Power Tools",
        "Commercial Vehicles",
        "Tools & Tackles",
        "Properties",
        "Industrial Equipment",
        "Warehouse & Storage",
        "Cargo & Shipping",
        "Machineries",
        "Musical Instruments",
        "Office and Business Essentials"
    ), nullable=False)

    subcategory = db.Column(db.String(100), nullable=True)
    name             = db.Column(db.String(200), nullable=False)
    description      = db.Column(db.Text, nullable=True)

    # At least ONE of these three is required (enforced in route, not DB) -
    # vendor chooses hour and/or km and/or day and/or month, none individually mandatory.
    rent_per_hour    = db.Column(db.Numeric(10, 2), nullable=True)
    rent_per_km       = db.Column(db.Numeric(10, 2), nullable=True)
    rent_per_day     = db.Column(db.Numeric(10, 2), nullable=True)
    rent_per_month   = db.Column(db.Numeric(10, 2), nullable=True)
    security_deposit = db.Column(db.Numeric(10, 2), nullable=True)

    # Location (copied from vendor on create, editable)
    pincode          = db.Column(db.String(6),   nullable=True)
    state            = db.Column(db.String(100), nullable=True)
    city             = db.Column(db.String(100), nullable=True)
    area             = db.Column(db.String(200), nullable=True)

    # Up to 5 image URLs from S3 - original size, no crop (handled in upload util)
    image1           = db.Column(db.String(500), nullable=True)
    image2           = db.Column(db.String(500), nullable=True)
    image3           = db.Column(db.String(500), nullable=True)
    image4           = db.Column(db.String(500), nullable=True)
    image5           = db.Column(db.String(500), nullable=True)

    # Share link - short unique slug, e.g. /p/aB3xK9
    share_slug       = db.Column(db.String(20), unique=True, nullable=True)

    # Stats
    click_count      = db.Column(db.Integer, default=0, nullable=False)
    is_active        = db.Column(db.Boolean, default=True)
    admin_reviewed   = db.Column(db.Boolean, default=False ,nullable=False)  
    deactivated_by = db.Column(db.Enum("vendor", "admin", "plan_expired"), nullable=True, default=None)
    edit_deadline    = db.Column(db.DateTime, nullable=True)
    # Chat/availability tracking - set when a user starts a chat about this
    # product, used to periodically nudge vendor "still available?"
    last_inquiry_at         = db.Column(db.DateTime, nullable=True)
    last_availability_check = db.Column(db.DateTime, nullable=True)

    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = db.relationship("Vendor", backref="products")
    def is_admin_flagged(self):
        return self.deactivated_by == "admin"

    def is_vendor_deactivated(self):
        return self.deactivated_by == "vendor"

    def edit_days_remaining(self):
        if not self.edit_deadline:
            return None
        delta = self.edit_deadline - datetime.utcnow()
        return max(0, delta.days)
    
    def _get_latest_strike_reason(self):
        if self.deactivated_by != "admin":
            return None
        from models.vendor import VendorStrike
        strike = VendorStrike.query.filter_by(
            product_id=self.id
        ).order_by(VendorStrike.created_at.desc()).first()
        return strike.reason if strike else None
    
    def image_urls(self):
        return [u for u in [self.image1, self.image2, self.image3,
                             self.image4, self.image5] if u]
    
    def is_newest_three(self):
        """True if this product is among the 3 newest active ones for its vendor."""
        top3 = Product.query.filter_by(
            vendor_id=self.vendor_id,
            is_active=True
        ).order_by(Product.click_count.desc()).limit(3).all()
        return self.id in [p.id for p in top3]

    @staticmethod
    def generate_share_slug():
        return secrets.token_urlsafe(6)[:8]

    def to_dict(self, include_vendor_badge=False):
        data = {
            "id": self.id, "name": self.name, "description": self.description,
            "category": self.category, "subcategory": self.subcategory,
            "rent_per_hour": str(self.rent_per_hour) if self.rent_per_hour else None,
            "rent_per_km": str(self.rent_per_km) if self.rent_per_km else None,
            "rent_per_day": str(self.rent_per_day) if self.rent_per_day else None,
            "rent_per_month": str(self.rent_per_month) if self.rent_per_month else None,
            "security_deposit": str(self.security_deposit) if self.security_deposit else None,
            "pincode": self.pincode, "state": self.state,
            "city": self.city, "area": self.area,
            "images": self.image_urls(),
            "share_slug": self.share_slug,
            "click_count": self.click_count,
            "is_active": self.is_active,
            "deactivated_by": self.deactivated_by,
            "strike_reason": self._get_latest_strike_reason(),
            "edit_deadline": str(self.edit_deadline) if self.edit_deadline else None,
            "edit_days_remaining": self.edit_days_remaining(),
            "created_at": str(self.created_at),
        }
        if include_vendor_badge and self.vendor:
            data["vendor_badge"] = self.vendor.badge()
            data["vendor_name"] = self.vendor.name
        return data


class ProductInquiry(db.Model):
    """Logs every time a user starts a chat/inquiry on a product.
    Used to track which active listings have buyer interest, so we can
    periodically prompt the vendor to confirm if it's still available
    (and auto-deactivate stale ones from the public listing)."""
    __tablename__ = "product_inquiries"

    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    product_id  = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    vendor_id   = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    user_id     = db.Column(db.Integer, nullable=False)  # FK to users table
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship("Product", backref="inquiries")


PRODUCT_CATEGORIES = {

    "Construction Equipment": [
        "Excavator / JCB",
        "Backhoe Loader",
        "Concrete Mixer",
        "Scaffolding & Shuttering",
        "Crane (Mobile / Tower)",
        "Road Roller / Compactor",
        "Generator (site use)",
        "Dump Truck / Tipper"
        "Portable Cabins"
    ],

    "Furniture & Home Appliances": [
        "Bed + Mattress",
        "Sofa / Sectional",
        "Wardrobe",
        "Dining Table + Chairs",
        "Refrigerator",
        "Washing Machine",
        "Air Conditioner",
        "Television"
    ],

    "Photography & Content Creator Gear": [
        "DSLR / Mirrorless Camera",
        "Drone",
        "Ring Light / Softbox Kit",
        "Gimbal / Stabilizer",
        "Microphone (lapel or shotgun)",
        "Green Screen Setup",
        "Camera Lens (wide, telephoto, macro)",
        "Podcast / Streaming Kit"
    ],

    "Events & Weddings": [
        "Mandap / Wedding Stage",
        "Shamiyana / Tent Structure",
        "PA Sound System + DJ Setup",
        "LED Video Wall",
        "Banquet Chairs + Tables",
        "Stage Lighting Rig",
        "Flower Decoration Setup",
        "Portable Generator (event backup)"
    ],

    "Fashion & Designer Wear": [
        "Bridal Lehenga",
        "Sherwani (bridal + guest)",
        "Designer Saree",
        "Cocktail Gown",
        "Bridal Jewellery Set",
        "Fancy Dress / Themed Costume",
        "Indo-Western Coord Set"
    ],

    "Agricultural Equipment": [
        "Tractor",
        "Rotavator",
        "Combine Harvester",
        "Seed Drill",
        "Sprayer (power / drone)",
        "Water Pump",
        "Thresher / Reaper Binder"
    ],

    "Passenger Vehicles": [
        "Hatchback (self-drive)",
        "Sedan (self-drive)",
        "SUV / MUV",
        "Luxury Car (wedding / event)",
        "Electric Car",
        "7-Seater Van"
    ],

    "Bikes & Scooters": [
        "Standard Scooter",
        "Cruiser Bike (Royal Enfield)",
        "Sports Bike",
        "Electric Scooter",
        "Electric Bike",
        "Delivery / Cargo Bike"
    ],

    "Medical Equipment": [
        "Hospital Bed (fowler / electric)",
        "Wheelchair (manual / motorized)",
        "Oxygen Concentrator",
        "BiPAP / CPAP Machine",
        "Nebulizer",
        "DVT / CPM Machine (rehab)",
        "Walker / Crutches"
    ],

    "Baby & Kids Gear": [
        "Crib / Cot",
        "Stroller / Pram",
        "Car Seat",
        "High Chair",
        "Baby Bouncer / Rocker",
        "Breast Pump",
        "Baby Carrier / Wrap"
    ],

    "Adventure & Trekking Gear": [
        "Sleeping Bag",
        "Camping Tent",
        "Down Jacket / Snow Gear",
        "Trekking Backpack",
        "Trekking Poles",
        "Trekking Shoes",
        "Camp Stove + Cooking Kit"
    ],

    "Sports & Fitness Equipment": [
        "Treadmill",
        "Exercise / Spin Bike",
        "Adjustable Dumbbells Set",
        "Multi-station Home Gym",
        "Table Tennis Table",
        "Cricket Kit",
        "Badminton / Sports Net Set"
    ],

    "Electrical & Power Tools": [
        "Electric Drill / Hammer Drill",
        "Angle Grinder",
        "Welding Machine",
        "Circular Saw / Jigsaw",
        "Pressure Washer",
        "Portable Generator (home use)",
        "Tile Cutter"
    ],

    "Commercial Vehicles": [
        "Mini Truck / Tempo (Tata Ace)",
        "Pickup Truck",
        "Medium Truck (8–12 tonne)",
        "Refrigerated Van",
        "Car Carrier",
        "Tipper (small, home construction)"
    ],

    "Tools & Tackles": [
        "Basic Hand Tool Kit (hammer, screwdrivers, pliers)",
        "Plumbing Tool Set",
        "Ladder (aluminium / telescopic)",
        "Spray Paint Gun",
        "Drain Snake / Pipe Auger",
        "Safety Harness + Rope",
        "Nail Gun / Staple Gun"
    ],

    "Properties": [
        "Co-working Desk / Hot Desk",
        "Private Cabin / Office",
        "Meeting Room (hourly)",
        "Banquet Hall",
        "Farmhouse / Lawn (event)",
        "Pop-up Retail Kiosk",
        "Conference / Training Hall"
    ],

    "Industrial Equipment": [
        "Forklift",
        "Mobile Crane",
        "Scissor Lift / Boom Lift",
        "Air Compressor (industrial)",
        "Diesel Generator (100–500 KVA)",
        "Conveyor Belt (portable)",
        "Industrial Pressure Washer"
    ],

    "Warehouse & Storage": [
        "Dry General Storage Unit",
        "Cold Storage / Refrigerated Space",
        "E-commerce Fulfilment Bay",
        "Document Storage Room",
        "Seasonal Overflow Space",
        "Event Equipment Storage Bay"
    ],

    "Cargo & Shipping": [
        "Mini Truck (1–2 tonne)",
        "Heavy Truck (10–25 tonne)",
        "Flatbed Trailer",
        "Refrigerated Truck",
        "ODC / Over-dimensional Trailer",
        "Tanker Truck"
    ],

    "Machineries": [
        "Fabric / Textile Printing Machine",
        "Packaging / Sealing Machine",
        "CNC / Lathe Machine",
        "Hydraulic Press",
        "Industrial Weighing Scale",
        "Injection Moulding Machine"
    ],
    
    "Musical Instruments": [
        "Acoustic Guitar",
        "Electric Guitar",
        "Piano",
        "Drums",
        "Violin",
        "Flute",
        "Saxophone"
    ],
    "Office and Business Essentials": [
        "Laptop / MacBook",
        "Projector & Screen",
        "Printer / Scanner",
        "DSLR / Webcam (video calls)",
        "Standing Desk",
        "Ergonomic Chair",
        "Whiteboard / Flipchart"
    ]
}

class VendorStrike(db.Model):
    """Log of every product removal / strike issued to a vendor.
    Kept even after unflagging, for admin history reference."""
    __tablename__ = "vendor_strikes"

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    vendor_id    = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    admin_id     = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=False)
    product_id   = db.Column(db.Integer, nullable=True)  # nullable - product itself gets deleted
    product_name = db.Column(db.String(200), nullable=True)  # snapshot, in case product is deleted
    reason       = db.Column(db.Text, nullable=False)
    strike_number = db.Column(db.Integer, nullable=False)  # 1, 2, or 3 at time of issue
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    vendor = db.relationship("Vendor", backref="strikes")