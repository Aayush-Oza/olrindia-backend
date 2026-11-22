# generate_sitemap.py - generates sitemap-products.xml and sitemap-vendors.xml
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from extensions import db
from models.vendor import Product, Vendor

PRODUCTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "frontend", "sitemap-products.xml"
)

VENDORS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "frontend", "sitemap-vendors.xml"
)

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-',
        (text or '').lower().replace('&', 'and')
    ).strip('-')

def generate_products():
    rows = (
        db.session.query(Product, Vendor)
        .join(Vendor, Product.vendor_id == Vendor.id)
        .filter(
            Product.is_active  == True,
            Vendor.is_active   == True,
            Vendor.is_verified == True,
        )
        .all()
    )

    urls = []
    for p, v in rows:
        cat  = slugify(p.category or '')
        city = slugify(p.city or 'india')
        slug = p.share_slug
        loc  = f"https://olrindia.com/product/{cat}/{city}/{slug}"
        urls.append(f"""  <url>
    <loc>{loc}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    with open(PRODUCTS_PATH, "w", encoding="utf-8") as f:
        f.write(xml)

    print(f"✅ Wrote {len(rows)} products to {PRODUCTS_PATH}")

def generate_vendors():
    vendors = Vendor.query.filter(
        Vendor.is_active   == True,
        Vendor.is_verified == True,
        Vendor.store_slug  != None,
    ).all()

    urls = []
    for v in vendors:
        loc = f"https://olrindia.com/vendor/{v.store_slug}"
        urls.append(f"""  <url>
    <loc>{loc}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    with open(VENDORS_PATH, "w", encoding="utf-8") as f:
        f.write(xml)

    print(f"✅ Wrote {len(vendors)} vendors to {VENDORS_PATH}")

def generate():
    with app.app_context():
        generate_products()
        generate_vendors()

if __name__ == "__main__":
    generate()