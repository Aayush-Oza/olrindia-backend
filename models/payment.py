# OLR India - Payment Model
# Tracks every Razorpay payment attempt by vendors (success and failure)
# This is your audit log - never delete rows from here

from datetime import datetime
from extensions import db


class VendorPayment(db.Model):
    __tablename__ = "vendor_payments"

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    vendor_id       = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)

    # Plan purchased
    plan            = db.Column(
        db.Enum("starter", "growth", "premium"),
        nullable=False
    )
    amount_inr      = db.Column(db.Numeric(10, 2), nullable=False)

    # Razorpay identifiers
    razorpay_order_id   = db.Column(db.String(100), unique=True, nullable=False)
    razorpay_payment_id = db.Column(db.String(100), nullable=True)   # Set on success
    razorpay_signature  = db.Column(db.String(300), nullable=True)   # Set on success

    # "created" → order made but payment not done yet
    # "paid"    → payment verified and plan activated
    # "failed"  → payment failed on Razorpay side
    status = db.Column(db.Enum("created", "paid", "failed", "cancelled", "superseded"), default="created", nullable=False)
    # Add these two columns to VendorPayment class
    period_start    = db.Column(db.DateTime, nullable=True)   # When this plan period starts
    period_end      = db.Column(db.DateTime, nullable=True)   # When this plan period ends
    # Duration of this payment cycle in days (30 for all plans currently)
    duration_days   = db.Column(db.Integer, default=30, nullable=False)

    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at         = db.Column(db.DateTime, nullable=True)   # Set when status → paid

    vendor = db.relationship("Vendor", backref="payments")