import re
import time
from typing import Dict, List
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from database import normalize_website, recommend_offer

SOCIAL_DOMAINS = {
    "facebook.com": "facebook_url",
    "instagram.com": "instagram_url",
    "linkedin.com": "linkedin_url",
    "tiktok.com": "tiktok_url",
    "youtube.com": "youtube_url",
    "youtu.be": "youtube_url",
}

COMMON_CONTACT_PATHS = ["/contact", "/contact-us", "/about", "/about-us"]


def _safe_get(url: str, timeout: int = 10):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
    }
    start = time.time()
    res = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    elapsed_ms = int((time.time() - start) * 1000)
    return res, elapsed_ms


def _extract_emails(text: str) -> List[str]:
    emails = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text or "")
    blocked = {"example.com", "domain.com", "email.com"}
    clean = []
    for email in emails:
        e = email.lower().strip(".,;:)")
        if any(e.endswith("@" + b) for b in blocked):
            continue
        if e not in clean:
            clean.append(e)
    return clean[:5]


def _find_socials(soup: BeautifulSoup, base_url: str) -> Dict[str, str]:
    found = {v: "" for v in SOCIAL_DOMAINS.values()}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href"))
        netloc = urlparse(href).netloc.lower().replace("www.", "")
        for domain, field in SOCIAL_DOMAINS.items():
            if domain in netloc and not found[field]:
                found[field] = href
    return found


def _analyze_html(html: str, base_url: str) -> Dict:
    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    emails = _extract_emails(text + " " + " ".join([a.get("href", "") for a in soup.find_all("a", href=True)]))
    socials = _find_socials(soup, base_url)
    forms = soup.find_all("form")
    has_contact_form = any(
        any(token in str(form).lower() for token in ["contact", "message", "email", "name", "phone", "appointment", "booking"])
        for form in forms
    )
    has_whatsapp = any("wa.me" in a.get("href", "") or "whatsapp" in a.get("href", "").lower() for a in soup.find_all("a", href=True))
    has_viewport = bool(soup.find("meta", attrs={"name": re.compile("viewport", re.I)}))
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    return {
        "email": emails[0] if emails else "",
        "emails_found": ", ".join(emails),
        "has_contact_form": has_contact_form,
        "has_whatsapp_button": has_whatsapp,
        "has_mobile_viewport": has_viewport,
        "title": title,
        **socials,
    }


def audit_website(website: str, business_name: str = "") -> Dict:
    website = normalize_website(website)
    if not website:
        return {
            "available": False,
            "website": "",
            "final_url": "",
            "website_status": "No Website",
            "website_quality_score": 0,
            "website_issues": "No website found.",
            "suggested_offer": "Website Setup",
        }

    result = {
        "available": False,
        "website": website,
        "final_url": website,
        "status_code": None,
        "website_status": "Unavailable",
        "website_quality_score": 0,
        "website_issues": "",
        "website_speed_ms": None,
        "has_ssl": website.startswith("https://"),
        "has_mobile_viewport": False,
        "has_contact_form": False,
        "has_whatsapp_button": False,
        "email": "",
        "facebook_url": "",
        "instagram_url": "",
        "linkedin_url": "",
        "tiktok_url": "",
        "youtube_url": "",
        "suggested_offer": "Website Redesign",
    }

    try:
        res, elapsed = _safe_get(website)
        result["available"] = True
        result["final_url"] = res.url
        result["status_code"] = res.status_code
        result["website_speed_ms"] = elapsed
        result["has_ssl"] = res.url.startswith("https://")
        html = res.text if "text/html" in res.headers.get("content-type", "") or "<html" in res.text[:500].lower() else ""
        page_data = _analyze_html(html, res.url) if html else {}
        result.update(page_data)

        # Try common contact pages only if email/form is missing.
        parsed = urlparse(res.url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        if not result.get("email") or not result.get("has_contact_form"):
            for path in COMMON_CONTACT_PATHS:
                try:
                    c_res, _ = _safe_get(urljoin(root, path), timeout=7)
                    if c_res.status_code >= 400:
                        continue
                    extra = _analyze_html(c_res.text, c_res.url)
                    for key, value in extra.items():
                        if value and not result.get(key):
                            result[key] = value
                    if result.get("email") and result.get("has_contact_form"):
                        break
                except Exception:
                    continue

        issues = []
        score = 100
        if res.status_code >= 400:
            issues.append(f"Website returned HTTP {res.status_code}.")
            score -= 35
        if not result["has_ssl"]:
            issues.append("SSL/HTTPS is missing.")
            score -= 15
        if not result.get("has_mobile_viewport"):
            issues.append("Mobile viewport meta tag missing; site may not be mobile-friendly.")
            score -= 20
        if not result.get("has_contact_form"):
            issues.append("Contact or appointment form not detected.")
            score -= 10
        if not result.get("has_whatsapp_button"):
            issues.append("WhatsApp/direct chat button not detected.")
            score -= 5
        if elapsed > 3500:
            issues.append("Website response looks slow.")
            score -= 15
        if not result.get("email"):
            issues.append("Public email not detected on website/contact pages.")
            score -= 5
        score = max(0, min(100, score))
        result["website_quality_score"] = score
        result["website_issues"] = " ".join(issues) if issues else "No major issues detected."
        result["website_status"] = "Good Website" if score >= 75 else "Needs Redesign"
        result["suggested_offer"] = "Google Business Profile Optimization" if score >= 75 else "Website Redesign"
        return result
    except Exception as exc:
        result["website_issues"] = f"Website could not be checked: {exc}"
        result["website_status"] = "Unavailable"
        result["suggested_offer"] = "Website Redesign"
        return result
