# OLR India - Main Application Entry Point
# Run with: python app.py (development)
# Run with: gunicorn app:app (production on AWS EC2)

import os
from flask import Flask, jsonify,request
from flask_cors import CORS

from config import config
from extensions import db, jwt, migrate,limiter
from utils.translate import translate_all_strings
# ── Import Models (needed for flask db migrate to detect tables) ──────────────
from models.user import User, UserVerificationToken, UserPasswordResetToken
from models.vendor import Vendor, VendorVerificationToken, VendorPasswordResetToken
from models.admin import Admin
from models.payment import VendorPayment
from flask_limiter.errors import RateLimitExceeded

# ── Import Blueprints ─────────────────────────────────────────────────────────
from routes.auth.user_auth import user_auth_bp
from routes.auth.vendor_auth import vendor_auth_bp
from routes.public import public_bp
from routes.seo import seo_bp
from routes.auth.admin_auth import admin_auth_bp

def create_app(env=None):
    """
    Application factory - creates and configures Flask app.
    """
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
    # ── Load Config ───────────────────────────────────────────────────────────
    env = env or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config[env])

    # ── Initialize Extensions ─────────────────────────────────────────────────
    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    
    @app.before_request
    def auto_translate_input():
        if request.method not in ('POST', 'PUT', 'PATCH'):
            return
        if not request.is_json:
            return
        try:
            data = request.get_json(silent=True, force=True)
            if data:
                translated = translate_all_strings(data)
                request._cached_json = (translated, translated)
        except Exception:
            pass
    # ── CORS Setup ────────────────────────────────────────────────────────────
    # Allow frontend to talk to backend
    # In production replace with actual domain
    CORS(app,
        origins=[
            "https://olrindia.com",
            "https://www.olrindia.com",
        ],
        supports_credentials=True
    )

    # ── Register Blueprints (Routes) ──────────────────────────────────────────
    app.register_blueprint(user_auth_bp,   url_prefix="/auth/user")
    app.register_blueprint(vendor_auth_bp, url_prefix="/auth/vendor")
    app.register_blueprint(public_bp, url_prefix="/products")
    app.register_blueprint(admin_auth_bp, url_prefix="/auth/admin")
    app.register_blueprint(seo_bp, url_prefix="")

    # ── JWT Error Handlers ────────────────────────────────────────────────────
    @jwt.unauthorized_loader
    def unauthorized_callback(error):
        print("UNAUTHORIZED:", error)
        return jsonify({
            "success": False,
            "message": error
        }), 401

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        return jsonify({
            "success": False,
            "message": "Too many requests. Please slow down and try again."
        }), 429
        
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({
            "success": False,
            "message": "Token has expired. Please refresh.",
            "expired": True
        }), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        print("INVALID TOKEN:", error)
        return jsonify({
            "success": False,
            "message": error
        }), 401

    @app.route('/.well-known/assetlinks.json')
    def assetlinks():
        data = [{
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.olrindia.app",
                "sha256_cert_fingerprints": [
                    "CB:90:41:16:37:05:4C:89:1A:9D:30:3C:89:EF:FC:27:C2:C1:53:06:9D:85:EE:1C:A1:1C:CD:6E:00:65:8B:A6",
                    "3A:E8:38:7D:7B:56:EC:D9:6A:3E:EE:59:09:FE:B6:FD:F2:D5:C8:4B:B2:72:E6:F4:4A:01:25:35:E6:7D:9E:17"
                ]
            }
        }]
        from flask import Response
        import json
        resp = Response(json.dumps(data), mimetype='application/json')
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
    # ── Health Check ──────────────────────────────────────────────────────────
    @app.route("/health", methods=["GET"])
    def health():
        """
        Health check endpoint.
        Use this to verify server is running.
        GET http://localhost:5000/health
        """
        return jsonify({
            "success": True,
            "message": "OLR India API is running.",
            "env": env
        }), 200

    # ── 404 Handler ───────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            "success": False,
            "message": "Route not found."
        }), 404

    # ── 405 Handler ───────────────────────────────────────────────────────────
    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({
            "success": False,
            "message": "Method not allowed."
        }), 405

    return app

# ── Run App ───────────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",   # Accept connections from any IP
        port=5000,         # Flask runs on port 5000
        debug=True         # Auto-reload on code changes
    )