# OLR India - Extensions
# All Flask extensions initialized here
# Imported into app.py and used across the project
# This avoids circular imports

from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import redis

cache = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# ── Database ──────────────────────────────────────────────────────────────────
# SQLAlchemy instance - used in all models
# Import this in models: from extensions import db
db = SQLAlchemy()

# ── JWT ───────────────────────────────────────────────────────────────────────
# JWTManager instance - handles all token operations
# Import this wherever JWT needed: from extensions import jwt
jwt = JWTManager()

# ── Database Migrations ───────────────────────────────────────────────────────
# Flask-Migrate - handles DB schema changes
# Use: flask db init, flask db migrate, flask db upgrade
migrate = Migrate()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://"
)