# OLR India - User Model
# Represents the users table in MySQL
# Users = customers who browse and contact vendors

import secrets
from datetime import datetime, timedelta
from extensions import db


class User(db.Model):
    __tablename__ = "users"

    # ── Primary Key ───────────────────────────────────────────────────────────
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # ── Basic Info ────────────────────────────────────────────────────────────
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    mobile = db.Column(db.String(15), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)

    # ── Location ──────────────────────────────────────────────────────────────
    # User enters pincode → postalpincode.in auto fills state, city, area
    pincode = db.Column(db.String(6), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    area = db.Column(db.String(200), nullable=True)
    # Browser geolocation - optional, used for nearby product search
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    # ── Profile ───────────────────────────────────────────────────────────────
    profile_photo = db.Column(db.String(500), nullable=True)  # S3 URL

    # ── Account Status ────────────────────────────────────────────────────────
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), default="user")

    # ── Social Login ──────────────────────────────────────────────────────────
    google_id = db.Column(db.String(200), unique=True, nullable=True)

    # ── FCM ───────────────────────────────────────────────────────────────────
    fcm_token = db.Column(db.String(500), nullable=True)
    
    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserVerificationToken(db.Model):
    """Magic link tokens for email verification"""
    __tablename__ = "user_verification_tokens"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="verification_tokens")

    @staticmethod
    def generate(user_id):
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        return UserVerificationToken(
            user_id=user_id,
            token=token,
            expires_at=expires_at
        )

    def is_valid(self):
        return (
            not self.is_used and
            datetime.utcnow() < self.expires_at
        )


class UserPasswordResetToken(db.Model):
    """Password reset link tokens"""
    __tablename__ = "user_password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="password_reset_tokens")

    @staticmethod
    def generate(user_id):
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        return UserPasswordResetToken(
            user_id=user_id,
            token=token,
            expires_at=expires_at
        )

    def is_valid(self):
        return (
            not self.is_used and
            datetime.utcnow() < self.expires_at
        )
        
class Wishlist(db.Model):
    __tablename__ = "wishlists"
    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, nullable=False)  # FK to products table later
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", backref="wishlist_items")