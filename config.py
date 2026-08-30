# OLR India - Configuration
# Loads all settings from .env file

import os
from datetime import timedelta
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Config:
    # ── Flask ─────────────────────────────────────────────────────────────────
    SECRET_KEY = os.getenv("SECRET_KEY")
    DEBUG = os.getenv("FLASK_DEBUG", "False") == "True"
    API_URL_PREFIX = os.getenv("API_URL_PREFIX", "")

    # ── Database (AWS RDS MySQL) ──────────────────────────────────────────────
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT", "3306")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")

    # SQLAlchemy connection string
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # Saves memory - always False

    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 3600,
    }

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 15))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))
    )
    JWT_TOKEN_LOCATION = ["cookies"]           # Read JWT from cookies only
    JWT_COOKIE_SECURE = False                  # True in production (HTTPS only)
    JWT_COOKIE_HTTPONLY = True                 # JS cannot access cookies - XSS safe
    JWT_COOKIE_SAMESITE = "Lax"               # CSRF protection
    JWT_COOKIE_CSRF_PROTECT = False            # We handle CSRF manually

    # ── Resend (Email) ────────────────────────────────────────────────────────
    RESEND_API_KEY = os.getenv("RESEND_API_KEY")
    RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL")
    
    # ── AWS S3 ────────────────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_S3_BUCKET         = os.getenv("AWS_S3_BUCKET")
    AWS_S3_REGION         = os.getenv("AWS_S3_REGION", "ap-south-1")

    # ── Frontend URL (for magic links in emails) ──────────────────────────────
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")

    #-Razorpay---
    RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    # ── SMS OTP (commented - enable when DLT registration done) ──────────────
    # MSG91_API_KEY = os.getenv("MSG91_API_KEY")
    # MSG91_SENDER_ID = os.getenv("MSG91_SENDER_ID")
    # MSG91_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID")

class DevelopmentConfig(Config):
    """Development specific settings"""
    DEBUG = True
    JWT_COOKIE_SECURE = False    # HTTP allowed in development
    API_URL_PREFIX = ""


class ProductionConfig(Config):
    """Production specific settings"""
    DEBUG = False
    JWT_COOKIE_SECURE = True     # HTTPS only in production
    JWT_COOKIE_SAMESITE = "Strict"
    API_URL_PREFIX = "/api"        # Prefix all API routes with /api in production


# Load correct config based on environment
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig
}