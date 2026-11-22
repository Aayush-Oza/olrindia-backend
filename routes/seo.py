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

    # Real user - Nginx already serves product.html to them
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

@seo_bp.route("/vendor/<string:store_slug>", methods=["GET"])
@limiter.limit("60 per minute")
def vendor_seo(store_slug):

    if not is_crawler(request.headers.get("User-Agent", "")):
        return redirect(f"/vendor/{store_slug}", code=302)

    v = Vendor.query.filter_by(store_slug=store_slug, is_active=True, is_verified=True).first()
    if not v:
        return redirect("/")

    products  = Product.query.filter_by(vendor_id=v.id, is_active=True).all()
    total     = len(products)
    clean_url = f"https://olrindia.com/vendor/{store_slug}"
    image     = v.profile_photo or "https://olrindia.com/assets/og-banner.jpg"
    city_text = v.city or "India"
    title     = f"{v.name}'s Store – OLR India"
    desc      = f"Browse {total} active listing{'s' if total != 1 else ''} from {v.name} in {city_text} on OLR India. No middleman. Direct chat."

    categories = list(set(p.category for p in products if p.category))
    cat_text   = ", ".join(categories[:5]) if categories else "various products"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="geo.region" content="IN">
<meta name="geo.placename" content="{city_text}">
<meta name="language" content="English">
<meta http-equiv="content-language" content="en-IN">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="keywords" content="{v.name} rentals, {cat_text}, rent in {city_text}, OLR India vendor, {city_text} rentals">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
<link rel="canonical" href="{clean_url}">
<meta property="og:type" content="profile">
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
  "@type": "LocalBusiness",
  "@id": "{clean_url}",
  "name": "{v.name}",
  "description": "{desc}",
  "url": "{clean_url}",
  "image": "{image}",
  "address": {{
    "@type": "PostalAddress",
    "addressLocality": "{v.city or ''}",
    "addressRegion": "{v.state or ''}",
    "addressCountry": "IN"
  }},
  "memberOf": {{
    "@id": "https://olrindia.com/#organization"
  }}
}}
</script>
</head>
<body>
<h1>{v.name}'s Store on OLR India</h1>
<p>{desc}</p>
<p>Categories: {cat_text}</p>
<p>Based in {city_text}.</p>
<a href="{clean_url}">Visit {v.name}'s store</a>
</body>
</html>"""

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}