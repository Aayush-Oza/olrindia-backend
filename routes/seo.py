import re
from flask import Blueprint, request, redirect
from models.vendor import Product, Vendor
from extensions import limiter

seo_bp = Blueprint("seo", __name__)

CRAWLER_UA = [
    "googlebot", "bingbot", "slurp", "duckduckbot",
    "whatsapp", "facebookexternalhit", "twitterbot",
    "linkedinbot", "slackbot", "telegrambot",
    "discordbot", "pinterest", "skypeuripreview",
]

def is_crawler(ua):
    ua = (ua or "").lower()
    return any(bot in ua for bot in CRAWLER_UA)

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-',
        (text or '').lower().replace('&', 'and')
    ).strip('-')

@seo_bp.route("/product/<string:cat>/<string:city>/<string:slug>", methods=["GET"])
@limiter.limit("60 per minute")
def product_seo(cat, city, slug):

    # Real user — Nginx already serves product.html to them
    # This route only reached when Nginx passes crawler traffic here
    if not is_crawler(request.headers.get("User-Agent", "")):
        return redirect(f"/product/{cat}/{city}/{slug}", code=302)

    p = Product.query.filter_by(share_slug=slug, is_active=True).first()
    if not p:
        return redirect("/")

    v = Vendor.query.get(p.vendor_id)
    if not v or not v.is_active or not v.is_verified:
        return redirect("/")

    clean_url  = f"https://olrindia.com/product/{slugify(p.category)}/{slugify(p.city or 'india')}/{slug}"
    image      = p.image1 or "https://olrindia.com/assets/og-banner.jpg"
    city_text  = p.city or "India"
    price      = (
        f"₹{p.rent_per_hour}/hour"   if p.rent_per_hour  else
        f"₹{p.rent_per_day}/day"     if p.rent_per_day   else
        f"₹{p.rent_per_month}/month" if p.rent_per_month else
        f"₹{p.rent_per_km}/km"       if p.rent_per_km    else ""
    )
    title = f"{p.name} for Rent in {city_text} – OLR India"
    desc  = (
        f"{p.description[:140]}… {price} · Available on OLR India."
        if p.description else
        f"{p.category} for rent in {city_text}. {price} · No middleman. Direct chat with vendor on OLR India."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{clean_url}">
<meta property="og:type" content="product">
<meta property="og:site_name" content="OLR India">
<meta property="og:locale" content="en_IN">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{image}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{clean_url}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@olrindia">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{image}">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "{p.name}",
  "description": "{desc}",
  "image": "{image}",
  "url": "{clean_url}",
  "category": "{p.category}",
  "offers": {{
    "@type": "Offer",
    "priceCurrency": "INR",
    "price": "{p.rent_per_day or p.rent_per_hour or p.rent_per_month or 0}",
    "availability": "https://schema.org/InStock",
    "areaServed": "{city_text}",
    "seller": {{
      "@type": "Organization",
      "name": "{v.name}"
    }}
  }}
}}
</script>
</head>
<body>
<h1>{p.name} for Rent in {city_text}</h1>
<p>{desc}</p>
<p>Listed by {v.name} on OLR India.</p>
<a href="{clean_url}">View full listing</a>
</body>
</html>"""

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}