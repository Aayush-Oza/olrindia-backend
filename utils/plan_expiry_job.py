# utils/plan_expiry_job.py
# Run daily: checks expired plans, activates pending_plan if queued, else drops to free

from datetime import datetime, timedelta
from extensions import db
from models.vendor import Vendor, Product, PLAN_LIMITS

def run_expiry_check(app):
    with app.app_context():
        now = datetime.utcnow()

        # Find all vendors whose paid plan just expired
        expired_vendors = Vendor.query.filter(
            Vendor.subscription_plan.in_(["starter", "growth", "premium"]),
            Vendor.subscription_expires_at <= now
        ).all()

        for vendor in expired_vendors:

            if vendor.pending_plan and vendor.pending_plan in PLAN_LIMITS:
                # Vendor pre-paid a downgrade plan - activate it now
                vendor.subscription_plan       = vendor.pending_plan
                vendor.subscription_expires_at = now + timedelta(days=30)
                vendor.pending_plan            = None

                # Reactivate any plan_expired products within new plan's limit
                new_limit = PLAN_LIMITS[vendor.subscription_plan]["max_active_posts"]

                active_products = Product.query.filter_by(
                    vendor_id=vendor.id,
                    is_active=True
                ).order_by(Product.click_count.desc()).all()

                # Also reactivate previously deactivated ones, then trim to limit
                all_products = Product.query.filter_by(
                    vendor_id=vendor.id
                ).order_by(Product.click_count.desc()).all()

                reactivated = 0
                for p in all_products:
                    if p.deactivated_by == "plan_expired":
                        if new_limit is None or reactivated < new_limit:
                            p.is_active = True
                            p.deactivated_by = None
                            reactivated += 1

                # Now trim active products beyond new limit
                if new_limit is not None:
                    active_now = Product.query.filter_by(
                        vendor_id=vendor.id,
                        is_active=True
                    ).order_by(Product.click_count.desc()).all()

                    for i, p in enumerate(active_now):
                        if i >= new_limit:
                            p.is_active = False
                            p.deactivated_by = "plan_expired"

            else:
                # No pending plan - drop to free
                vendor.subscription_plan       = "free"
                vendor.subscription_expires_at = None
                vendor.pending_plan            = None

                free_limit = PLAN_LIMITS["free"]["max_active_posts"]  # 1

                active_products = Product.query.filter_by(
                    vendor_id=vendor.id,
                    is_active=True
                ).order_by(Product.click_count.desc()).all()

                if len(active_products) <= free_limit:
                    continue

                # Keep top N by clicks, deactivate the rest
                for p in active_products[free_limit:]:
                    p.is_active = False
                    p.deactivated_by = "plan_expired"

        db.session.commit()
        print(f"[{now}] Expiry check done. Processed {len(expired_vendors)} vendors.")

def check_single_vendor(vendor):
    """Instant expiry check on profile load - no waiting for cron."""
    now = datetime.utcnow()
    if vendor.subscription_plan not in ("starter", "growth", "premium"):
        return
    if not vendor.subscription_expires_at or vendor.subscription_expires_at > now:
        return

    if vendor.pending_plan and vendor.pending_plan in PLAN_LIMITS:
        vendor.subscription_plan       = vendor.pending_plan
        vendor.subscription_expires_at = now + timedelta(days=30)
        vendor.pending_plan            = None

        new_limit = PLAN_LIMITS[vendor.subscription_plan]["max_active_posts"]
        all_products = Product.query.filter_by(
            vendor_id=vendor.id
        ).order_by(Product.click_count.desc()).all()

        reactivated = 0
        for p in all_products:
            if p.deactivated_by == "plan_expired":
                if new_limit is None or reactivated < new_limit:
                    p.is_active = True
                    p.deactivated_by = None
                    reactivated += 1

        if new_limit is not None:
            active_now = Product.query.filter_by(
                vendor_id=vendor.id, is_active=True
            ).order_by(Product.click_count.desc()).all()
            for i, p in enumerate(active_now):
                if i >= new_limit:
                    p.is_active = False
                    p.deactivated_by = "plan_expired"
    else:
        vendor.subscription_plan       = "free"
        vendor.subscription_expires_at = None
        vendor.pending_plan            = None

        free_limit = PLAN_LIMITS["free"]["max_active_posts"]
        active_products = Product.query.filter_by(
            vendor_id=vendor.id, is_active=True
        ).order_by(Product.click_count.desc()).all()
        for p in active_products[free_limit:]:
            p.is_active = False
            p.deactivated_by = "plan_expired"

    db.session.commit()
    
if __name__ == "__main__":
    from app import create_app
    app = create_app()
    run_expiry_check(app)