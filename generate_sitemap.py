# generate_sitemap.py - standalone script, run manually. Not imported by app.py.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from extensions import db
from models.vendor import Product, Vendor

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "frontend", "sitemap-products.xml"
)

def generate():
    with app.app_context():
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
            loc = f"https://olrindia.com/p.html?slug={p.share_slug}"
            urls.append(f"""  <url>
    <loc>{loc}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>""")

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write(xml)

        print(f"✅ Wrote {len(rows)} products to {OUTPUT_PATH}")

if __name__ == "__main__":
    generate()