import os
import re
import sqlite3
from datetime import datetime, date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

DB_PATH = os.getenv("DATABASE_PATH", "data/leads.db")

CRM_STATUSES = [
    "New",
    "Message Sent",
    "Call Attempted",
    "Replied",
    "Interested",
    "Not Interested",
    "Follow Up Needed",
    "Converted",
    "Lost",
]

CONTACT_METHODS = ["", "WhatsApp", "Call", "Email"]
PRIORITIES = ["", "High", "Medium", "Low"]
PHONE_STATUSES = ["Valid", "Invalid", "Missing"]
EMAIL_STATUSES = ["Found", "Missing", "Invalid", "Unchecked"]
LEAD_QUALITIES = ["High", "Medium", "Low"]
WEBSITE_STATUSES = ["No Website", "Good Website", "Needs Redesign", "Unavailable", "Unchecked"]
SUGGESTED_OFFERS = [
    "Website Setup",
    "Website Redesign",
    "Google Business Profile Optimization",
    "Social Media Setup",
    "Website + SEO Package",
    "Follow-up Required",
]

PRESET_CATEGORIES = [
    "Dental Clinics",
    "Medical Clinics",
    "Restaurants",
    "Salons",
    "Gyms",
    "Real Estate Agents",
    "Car Repair Shops",
    "Schools",
    "Lawyers",
    "Construction Companies",
    "Hotels",
    "Pharmacies",
    "Plumbers",
    "Electricians",
    "HVAC Companies",
]

PRESET_CITIES = [
    "Lahore",
    "Karachi",
    "Islamabad",
    "Multan",
    "Faisalabad",
    "Rawalpindi",
    "Dubai",
    "London",
    "New York",
    "Houston",
    "Dallas",
    "Chicago",
]

LEAD_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "business_name": "TEXT NOT NULL",
    "phone": "TEXT",
    "phone_normalized": "TEXT",
    "phone_status": "TEXT DEFAULT 'Missing'",
    "email": "TEXT",
    "email_status": "TEXT DEFAULT 'Unchecked'",
    "address": "TEXT",
    "city": "TEXT",
    "category": "TEXT",
    "website": "TEXT",
    "has_website": "INTEGER DEFAULT 0",
    "website_status": "TEXT DEFAULT 'Unchecked'",
    "website_quality_score": "INTEGER DEFAULT 0",
    "website_issues": "TEXT",
    "website_speed_ms": "INTEGER",
    "has_ssl": "INTEGER DEFAULT 0",
    "has_mobile_viewport": "INTEGER DEFAULT 0",
    "has_contact_form": "INTEGER DEFAULT 0",
    "has_whatsapp_button": "INTEGER DEFAULT 0",
    "facebook_url": "TEXT",
    "instagram_url": "TEXT",
    "linkedin_url": "TEXT",
    "tiktok_url": "TEXT",
    "youtube_url": "TEXT",
    "google_map_link": "TEXT",
    "google_place_id": "TEXT",
    "rating": "REAL",
    "reviews_count": "INTEGER",
    "lead_score": "INTEGER DEFAULT 0",
    "lead_quality": "TEXT DEFAULT 'Low'",
    "status": "TEXT DEFAULT 'New'",
    "notes": "TEXT",
    "contact_method": "TEXT",
    "assigned_to": "TEXT",
    "priority": "TEXT",
    "source_query": "TEXT",
    "suggested_offer": "TEXT",
    "domain_suggestions": "TEXT",
    "campaign_id": "INTEGER",
    "created_at": "TEXT",
    "updated_at": "TEXT",
    "last_contacted_at": "TEXT",
    "next_follow_up_at": "TEXT",
    "last_audit_at": "TEXT",
    "duplicate_key": "TEXT",
}

SEARCH_JOB_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "job_id": "TEXT UNIQUE",
    "business_type": "TEXT",
    "city": "TEXT",
    "max_results": "INTEGER",
    "only_no_website": "INTEGER DEFAULT 1",
    "only_with_phone": "INTEGER DEFAULT 1",
    "total_found": "INTEGER DEFAULT 0",
    "saved_count": "INTEGER DEFAULT 0",
    "failed_count": "INTEGER DEFAULT 0",
    "status": "TEXT DEFAULT 'queued'",
    "message": "TEXT",
    "filters_used": "TEXT",
    "created_at": "TEXT",
    "started_at": "TEXT",
    "finished_at": "TEXT",
}

CAMPAIGN_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL",
    "description": "TEXT",
    "category": "TEXT",
    "city": "TEXT",
    "status": "TEXT DEFAULT 'Active'",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}

ACTIVITY_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "lead_id": "INTEGER NOT NULL",
    "activity_type": "TEXT",
    "note": "TEXT",
    "created_at": "TEXT",
}


def _ensure_parent() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_parent()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(cur: sqlite3.Cursor, table: str) -> List[str]:
    return [row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]


def _ensure_columns(cur: sqlite3.Cursor, table: str, columns: Dict[str, str]) -> None:
    existing = set(_table_columns(cur, table))
    for name, ddl in columns.items():
        if name not in existing and not ddl.upper().startswith("INTEGER PRIMARY KEY"):
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _create_table(cur: sqlite3.Cursor, table: str, columns: Dict[str, str]) -> None:
    cols = ",\n".join([f"{name} {ddl}" for name, ddl in columns.items()])
    cur.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
    _ensure_columns(cur, table, columns)


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()
    _create_table(cur, "leads", LEAD_COLUMNS)
    _create_table(cur, "search_jobs", SEARCH_JOB_COLUMNS)
    _create_table(cur, "campaigns", CAMPAIGN_COLUMNS)
    _create_table(cur, "activities", ACTIVITY_COLUMNS)

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city)",
        "CREATE INDEX IF NOT EXISTS idx_leads_category ON leads(category)",
        "CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone_normalized)",
        "CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)",
        "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)",
        "CREATE INDEX IF NOT EXISTS idx_leads_has_website ON leads(has_website)",
        "CREATE INDEX IF NOT EXISTS idx_leads_website_status ON leads(website_status)",
        "CREATE INDEX IF NOT EXISTS idx_leads_quality ON leads(lead_quality)",
        "CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(lead_score)",
        "CREATE INDEX IF NOT EXISTS idx_leads_followup ON leads(next_follow_up_at)",
        "CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign_id)",
        "CREATE INDEX IF NOT EXISTS idx_leads_duplicate_key ON leads(duplicate_key)",
        "CREATE INDEX IF NOT EXISTS idx_search_jobs_created ON search_jobs(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_activities_lead ON activities(lead_id)",
    ]
    for sql in indexes:
        cur.execute(sql)

    # Recalculate key fields for older rows after migrations.
    rows = cur.execute("SELECT * FROM leads").fetchall()
    for row in rows:
        d = dict(row)
        phone_info = validate_and_normalize_phone(d.get("phone"))
        website = normalize_website(d.get("website"))
        domain_suggestions = d.get("domain_suggestions") or suggest_domains(d.get("business_name"), d.get("city"))
        score, quality, priority = calculate_lead_score({**d, **phone_info, "website": website})
        duplicate_key = build_duplicate_key(
            d.get("business_name"), d.get("address"), phone_info.get("phone_normalized"), d.get("google_place_id")
        )
        suggested_offer = d.get("suggested_offer") or recommend_offer({**d, "website": website})
        cur.execute(
            """
            UPDATE leads
            SET phone=:phone, phone_normalized=:phone_normalized, phone_status=:phone_status,
                lead_score=:lead_score, lead_quality=:lead_quality,
                priority=COALESCE(NULLIF(priority, ''), :priority), duplicate_key=:duplicate_key,
                has_website=:has_website, website_status=COALESCE(NULLIF(website_status, ''), :website_status),
                suggested_offer=COALESCE(NULLIF(suggested_offer, ''), :suggested_offer),
                domain_suggestions=COALESCE(NULLIF(domain_suggestions, ''), :domain_suggestions),
                email_status=COALESCE(NULLIF(email_status, ''), :email_status)
            WHERE id=:id
            """,
            {
                "id": d["id"],
                "phone": phone_info["phone"],
                "phone_normalized": phone_info["phone_normalized"],
                "phone_status": phone_info["phone_status"],
                "lead_score": score,
                "lead_quality": quality,
                "priority": priority,
                "duplicate_key": duplicate_key,
                "has_website": 1 if website else 0,
                "website_status": "Unchecked" if website else "No Website",
                "suggested_offer": suggested_offer,
                "domain_suggestions": domain_suggestions,
                "email_status": "Found" if normalize_text(d.get("email")) else "Unchecked",
            },
        )

    conn.commit()
    conn.close()


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_website(website: Optional[str]) -> str:
    if not website:
        return ""
    website = normalize_text(website)
    if website.lower() in {"no website", "none", "n/a", "na", "website", "not available"}:
        return ""
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website
    return website


def _looks_like_rating_or_reviews(text: str) -> bool:
    lower = text.lower()
    if any(token in lower for token in ["star", "review", "rating", "rated"]):
        return True
    if re.search(r"\b\d(?:\.\d)?\s*\(?\d{1,6}\)?\b", text) and len(re.findall(r"\d", text)) < 9:
        return True
    single_digit_groups = re.findall(r"(?<!\d)\d(?!\d)", text)
    if len(single_digit_groups) >= 5 and re.search(r"\d\.\d", text):
        return True
    return False


def validate_and_normalize_phone(phone: Optional[str], default_country: str = "PK") -> Dict[str, str]:
    raw = normalize_text(phone)
    if not raw:
        return {"phone": "", "phone_normalized": "", "phone_status": "Missing"}

    cleaned = re.sub(r"(?i)^(phone|call|mobile|tel|telephone|whatsapp)[:\s-]*", "", raw).strip()
    cleaned = cleaned.replace("\u202a", "").replace("\u202c", "")

    if _looks_like_rating_or_reviews(cleaned):
        return {"phone": raw, "phone_normalized": "", "phone_status": "Invalid"}

    candidate_matches = re.findall(r"\+?\d[\d\s().-]{6,}\d", cleaned)
    candidate = max(candidate_matches, key=len) if candidate_matches else cleaned
    candidate = normalize_text(candidate)
    digits = re.sub(r"\D", "", candidate)
    had_plus = candidate.strip().startswith("+")

    if not (8 <= len(digits) <= 15):
        return {"phone": raw, "phone_normalized": "", "phone_status": "Invalid"}

    normalized = ""
    if digits.startswith("0092") and len(digits) >= 13:
        normalized = "+" + digits[2:]
    elif digits.startswith("92") and len(digits) == 12:
        normalized = "+" + digits
    elif digits.startswith("03") and len(digits) == 11:
        normalized = "+92" + digits[1:]
    elif digits.startswith("3") and len(digits) == 10 and default_country.upper() == "PK":
        normalized = "+92" + digits
    elif had_plus:
        normalized = "+" + digits
    elif len(digits) == 10:
        normalized = digits
    elif 8 <= len(digits) <= 15:
        normalized = digits

    if not normalized:
        return {"phone": raw, "phone_normalized": "", "phone_status": "Invalid"}

    return {"phone": normalized if normalized.startswith("+") else candidate, "phone_normalized": normalized, "phone_status": "Valid"}


def validate_email(email: Optional[str]) -> Tuple[str, str]:
    email = normalize_text(email).lower()
    if not email:
        return "", "Missing"
    if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", email):
        return email, "Found"
    return email, "Invalid"


def extract_place_id_from_link(link: Optional[str]) -> str:
    if not link:
        return ""
    link = unquote(str(link))
    match = re.search(r"!1s([^!]+)", link)
    if match:
        return match.group(1)[:160]
    match = re.search(r"/place/([^/?]+)", link)
    if match:
        return match.group(1)[:160]
    return ""


def _slug(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _domain_slug(value: Optional[str]) -> str:
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    stop = {"the", "and", "clinic", "clinics", "restaurant", "restaurants", "official", "pvt", "ltd", "llc", "inc"}
    clean = [w for w in words if w not in stop]
    return "".join(clean)[:28] or "business"


def suggest_domains(name: Optional[str], city: Optional[str] = "") -> str:
    base = _domain_slug(name)
    city_slug = _domain_slug(city) if city else ""
    options = [f"{base}.com", f"{base}.pk"]
    if city_slug and city_slug != "business":
        options.append(f"{base}{city_slug}.com")
    return ", ".join(dict.fromkeys(options))


def build_duplicate_key(name: Optional[str], address: Optional[str], phone_normalized: Optional[str], place_id: Optional[str]) -> str:
    if place_id:
        return f"place:{place_id}"
    if phone_normalized:
        return f"phone:{phone_normalized}"
    return f"nameaddr:{_slug(name)[:60]}:{_slug(address)[:80]}"


def calculate_lead_score(data: Dict[str, Any]) -> Tuple[int, str, str]:
    website = normalize_website(data.get("website"))
    has_website = bool(website or data.get("has_website") == 1)
    website_status = data.get("website_status") or "Unchecked"
    phone_status = data.get("phone_status") or "Missing"
    email_status = data.get("email_status") or ("Found" if data.get("email") else "Missing")
    rating = data.get("rating")
    reviews_count = data.get("reviews_count")
    address = normalize_text(data.get("address"))
    social_count = sum(1 for k in ["facebook_url", "instagram_url", "linkedin_url", "tiktok_url", "youtube_url"] if data.get(k))

    try:
        rating_value = float(rating) if rating not in (None, "") else None
    except (ValueError, TypeError):
        rating_value = None
    try:
        reviews_value = int(reviews_count) if reviews_count not in (None, "") else 0
    except (ValueError, TypeError):
        reviews_value = 0

    score = 0
    if not has_website:
        score += 40
    elif website_status in {"Needs Redesign", "Unavailable"}:
        score += 25
    if phone_status == "Valid":
        score += 30
    if email_status == "Found":
        score += 10
    if rating_value is not None and rating_value >= 4.5:
        score += 10
    if reviews_value >= 50:
        score += 10
    if address:
        score += 10
    if social_count == 0:
        score += 5
    score = min(score, 100)

    if score >= 80:
        return score, "High", "High"
    if score >= 50:
        return score, "Medium", "Medium"
    return score, "Low", "Low"


def recommend_offer(data: Dict[str, Any]) -> str:
    website = normalize_website(data.get("website"))
    status = data.get("website_status") or "Unchecked"
    social_count = sum(1 for k in ["facebook_url", "instagram_url", "linkedin_url", "tiktok_url", "youtube_url"] if data.get(k))
    if not website:
        return "Website Setup"
    if status in {"Needs Redesign", "Unavailable"}:
        return "Website Redesign"
    if social_count == 0:
        return "Social Media Setup"
    return "Google Business Profile Optimization"


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _slug(a), _slug(b)).ratio()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row) if row else {}


def upsert_lead(data: Dict[str, Any]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    website = normalize_website(data.get("website"))
    has_website = 1 if website else 0
    business_name = normalize_text(data.get("business_name") or data.get("name") or "")
    address = normalize_text(data.get("address") or "")
    if not business_name:
        raise ValueError("Business name is required")

    phone_info = validate_and_normalize_phone(data.get("phone"))
    email, email_status = validate_email(data.get("email"))
    if not data.get("email"):
        email_status = data.get("email_status") or "Unchecked"
    place_id = normalize_text(data.get("google_place_id") or extract_place_id_from_link(data.get("google_map_link")))
    website_status = data.get("website_status") or ("Unchecked" if website else "No Website")
    domain_suggestions = data.get("domain_suggestions") or suggest_domains(business_name, data.get("city"))

    payload = dict(data)
    payload.update(phone_info)
    payload.update({"email": email, "email_status": email_status, "website": website, "has_website": has_website, "website_status": website_status})
    score, quality, auto_priority = calculate_lead_score(payload)
    duplicate_key = build_duplicate_key(business_name, address, phone_info.get("phone_normalized"), place_id)
    suggested_offer = data.get("suggested_offer") or recommend_offer(payload)

    conn = get_connection()
    cur = conn.cursor()
    existing = None
    if place_id:
        existing = cur.execute("SELECT id FROM leads WHERE google_place_id = ? LIMIT 1", (place_id,)).fetchone()
    if not existing and phone_info.get("phone_normalized"):
        existing = cur.execute("SELECT id FROM leads WHERE phone_normalized = ? LIMIT 1", (phone_info["phone_normalized"],)).fetchone()
    if not existing and address:
        candidates = cur.execute("SELECT id, business_name FROM leads WHERE address = ? LIMIT 20", (address,)).fetchall()
        for row in candidates:
            if similar(row["business_name"], business_name) >= 0.72:
                existing = row
                break
    if not existing and duplicate_key:
        existing = cur.execute("SELECT id FROM leads WHERE duplicate_key = ? LIMIT 1", (duplicate_key,)).fetchone()

    record = {name: None for name in LEAD_COLUMNS.keys() if name != "id"}
    record.update({
        "business_name": business_name,
        "phone": phone_info["phone"],
        "phone_normalized": phone_info["phone_normalized"],
        "phone_status": phone_info["phone_status"],
        "email": email,
        "email_status": email_status,
        "address": address,
        "city": normalize_text(data.get("city")),
        "category": normalize_text(data.get("category")),
        "website": website,
        "has_website": has_website,
        "website_status": website_status,
        "website_quality_score": data.get("website_quality_score") or 0,
        "website_issues": normalize_text(data.get("website_issues")),
        "website_speed_ms": data.get("website_speed_ms"),
        "has_ssl": int(bool(data.get("has_ssl"))) if data.get("has_ssl") is not None else int(website.startswith("https://")),
        "has_mobile_viewport": int(bool(data.get("has_mobile_viewport"))) if data.get("has_mobile_viewport") is not None else 0,
        "has_contact_form": int(bool(data.get("has_contact_form"))) if data.get("has_contact_form") is not None else 0,
        "has_whatsapp_button": int(bool(data.get("has_whatsapp_button"))) if data.get("has_whatsapp_button") is not None else 0,
        "facebook_url": normalize_text(data.get("facebook_url")),
        "instagram_url": normalize_text(data.get("instagram_url")),
        "linkedin_url": normalize_text(data.get("linkedin_url")),
        "tiktok_url": normalize_text(data.get("tiktok_url")),
        "youtube_url": normalize_text(data.get("youtube_url")),
        "google_map_link": normalize_text(data.get("google_map_link")),
        "google_place_id": place_id,
        "rating": data.get("rating"),
        "reviews_count": data.get("reviews_count"),
        "lead_score": score,
        "lead_quality": quality,
        "status": data.get("status") or "New",
        "notes": normalize_text(data.get("notes")),
        "contact_method": data.get("contact_method") or "",
        "assigned_to": normalize_text(data.get("assigned_to")),
        "priority": data.get("priority") or auto_priority,
        "source_query": normalize_text(data.get("source_query")),
        "suggested_offer": suggested_offer,
        "domain_suggestions": domain_suggestions,
        "campaign_id": data.get("campaign_id"),
        "created_at": now,
        "updated_at": now,
        "last_contacted_at": data.get("last_contacted_at") or "",
        "next_follow_up_at": data.get("next_follow_up_at") or "",
        "last_audit_at": data.get("last_audit_at") or "",
        "duplicate_key": duplicate_key,
    })

    if existing:
        record["updated_at"] = now
        columns = [k for k in record.keys() if k not in {"created_at"}]
        set_clause = ", ".join([f"{k}=:{k}" for k in columns])
        record["id"] = existing["id"]
        cur.execute(f"UPDATE leads SET {set_clause} WHERE id=:id", record)
        lead_id = existing["id"]
        add_activity_raw(cur, lead_id, "Updated", "Lead details updated from scraper/import.", now)
    else:
        cols = list(record.keys())
        placeholders = ", ".join([":" + c for c in cols])
        cur.execute(f"INSERT INTO leads ({', '.join(cols)}) VALUES ({placeholders})", record)
        lead_id = cur.lastrowid
        add_activity_raw(cur, lead_id, "Created", "Lead collected and saved.", now)
    conn.commit()
    conn.close()
    return int(lead_id)


def add_activity_raw(cur: sqlite3.Cursor, lead_id: int, activity_type: str, note: str, now: Optional[str] = None) -> None:
    cur.execute(
        "INSERT INTO activities (lead_id, activity_type, note, created_at) VALUES (?, ?, ?, ?)",
        (lead_id, activity_type, note, now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def add_activity(lead_id: int, activity_type: str, note: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    add_activity_raw(cur, lead_id, activity_type, note)
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return int(rowid)


def list_activities(lead_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM activities WHERE lead_id=? ORDER BY created_at DESC, id DESC LIMIT ?", (lead_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lead(lead_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT l.*, c.name AS campaign_name
        FROM leads l
        LEFT JOIN campaigns c ON c.id = l.campaign_id
        WHERE l.id=?
        """,
        (lead_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["activities"] = list_activities(lead_id)
    return d


def _filters_to_where(filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
    clauses = []
    params: List[Any] = []
    q = normalize_text(filters.get("q"))
    if q:
        clauses.append("(l.business_name LIKE ? OR l.phone LIKE ? OR l.email LIKE ? OR l.address LIKE ? OR l.notes LIKE ?)")
        params.extend([f"%{q}%"] * 5)
    for col in ["city", "category", "status", "lead_quality", "phone_status", "email_status", "priority", "contact_method", "website_status", "assigned_to", "suggested_offer"]:
        value = normalize_text(filters.get(col))
        if value:
            clauses.append(f"l.{col} = ?")
            params.append(value)
    if normalize_text(filters.get("campaign_id")):
        clauses.append("l.campaign_id = ?")
        params.append(filters.get("campaign_id"))
    if str(filters.get("no_website", "")).lower() in {"1", "true", "yes"}:
        clauses.append("l.has_website = 0")
    if str(filters.get("has_phone", "")).lower() in {"1", "true", "yes"}:
        clauses.append("l.phone_status = 'Valid'")
    if str(filters.get("hot", "")).lower() in {"1", "true", "yes"}:
        clauses.append("l.lead_quality = 'High'")
    if str(filters.get("due_follow_up", "")).lower() in {"1", "true", "yes"}:
        today = date.today().strftime("%Y-%m-%d")
        clauses.append("l.next_follow_up_at != '' AND l.next_follow_up_at <= ?")
        params.append(today + " 23:59:59")
    if str(filters.get("no_social", "")).lower() in {"1", "true", "yes"}:
        clauses.append("COALESCE(l.facebook_url,'')='' AND COALESCE(l.instagram_url,'')='' AND COALESCE(l.linkedin_url,'')='' AND COALESCE(l.tiktok_url,'')='' AND COALESCE(l.youtube_url,'')=''")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def list_leads(filters: Dict[str, Any], page: int = 1, per_page: int = 25) -> Dict[str, Any]:
    page = max(1, int(page or 1))
    per_page = min(100, max(5, int(per_page or 25)))
    offset = (page - 1) * per_page
    where, params = _filters_to_where(filters)
    conn = get_connection()
    total = conn.execute(f"SELECT COUNT(*) FROM leads l {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT l.*, c.name AS campaign_name
        FROM leads l
        LEFT JOIN campaigns c ON c.id = l.campaign_id
        {where}
        ORDER BY l.lead_score DESC, l.updated_at DESC, l.id DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows], "page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)}


def update_lead(lead_id: int, **kwargs) -> bool:
    allowed = {k for k in LEAD_COLUMNS.keys() if k != "id"}
    payload = {k: v for k, v in kwargs.items() if k in allowed}
    if "phone" in payload:
        payload.update(validate_and_normalize_phone(payload.get("phone")))
    if "email" in payload:
        email, email_status = validate_email(payload.get("email"))
        payload["email"] = email
        payload["email_status"] = email_status
    if "website" in payload:
        payload["website"] = normalize_website(payload.get("website"))
        payload["has_website"] = 1 if payload["website"] else 0
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    cur = conn.cursor()
    current = cur.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not current:
        conn.close()
        return False
    merged = dict(current)
    merged.update(payload)
    score, quality, auto_priority = calculate_lead_score(merged)
    payload["lead_score"] = score
    payload["lead_quality"] = quality
    if not payload.get("priority") and not merged.get("priority"):
        payload["priority"] = auto_priority
    payload["suggested_offer"] = payload.get("suggested_offer") or recommend_offer(merged)
    if not merged.get("domain_suggestions"):
        payload["domain_suggestions"] = suggest_domains(merged.get("business_name"), merged.get("city"))

    set_clause = ", ".join([f"{k}=?" for k in payload])
    cur.execute(f"UPDATE leads SET {set_clause} WHERE id=?", list(payload.values()) + [lead_id])
    changes_note = ", ".join(payload.keys())
    add_activity_raw(cur, lead_id, "Updated", f"Lead updated: {changes_note}")
    conn.commit()
    conn.close()
    return True


def apply_audit_to_lead(lead_id: int, audit: Dict[str, Any]) -> bool:
    fields = {
        "website": audit.get("final_url") or audit.get("website") or "",
        "has_website": 1 if audit.get("available") else 0,
        "website_status": audit.get("website_status") or "Unavailable",
        "website_quality_score": audit.get("website_quality_score") or 0,
        "website_issues": audit.get("website_issues") or "",
        "website_speed_ms": audit.get("website_speed_ms"),
        "has_ssl": 1 if audit.get("has_ssl") else 0,
        "has_mobile_viewport": 1 if audit.get("has_mobile_viewport") else 0,
        "has_contact_form": 1 if audit.get("has_contact_form") else 0,
        "has_whatsapp_button": 1 if audit.get("has_whatsapp_button") else 0,
        "facebook_url": audit.get("facebook_url") or "",
        "instagram_url": audit.get("instagram_url") or "",
        "linkedin_url": audit.get("linkedin_url") or "",
        "tiktok_url": audit.get("tiktok_url") or "",
        "youtube_url": audit.get("youtube_url") or "",
        "email": audit.get("email") or "",
        "email_status": "Found" if audit.get("email") else "Missing",
        "suggested_offer": audit.get("suggested_offer") or "",
        "last_audit_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    ok = update_lead(lead_id, **fields)
    if ok:
        add_activity(lead_id, "Website Audit", f"Audit complete. Status: {fields['website_status']}. Issues: {fields['website_issues'] or 'None'}")
    return ok


def delete_lead(lead_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM activities WHERE lead_id=?", (lead_id,))
    cur.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_distinct_values(column: str) -> List[str]:
    if column not in LEAD_COLUMNS:
        return []
    conn = get_connection()
    rows = conn.execute(f"SELECT DISTINCT {column} FROM leads WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column} LIMIT 250").fetchall()
    conn.close()
    return [r[0] for r in rows]


def _count(cur: sqlite3.Cursor, sql: str, params: Tuple = ()) -> int:
    return int(cur.execute(sql, params).fetchone()[0] or 0)


def _group(cur: sqlite3.Cursor, column: str, limit: int = 8) -> List[Dict[str, Any]]:
    rows = cur.execute(
        f"SELECT COALESCE(NULLIF({column}, ''), 'Unknown') AS label, COUNT(*) AS value FROM leads GROUP BY label ORDER BY value DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"label": r["label"], "value": r["value"]} for r in rows]


def get_stats() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()
    total = _count(cur, "SELECT COUNT(*) FROM leads")
    converted = _count(cur, "SELECT COUNT(*) FROM leads WHERE status='Converted'")
    today = date.today().strftime("%Y-%m-%d")
    stats = {
        "total": total,
        "no_website": _count(cur, "SELECT COUNT(*) FROM leads WHERE has_website=0"),
        "with_phone": _count(cur, "SELECT COUNT(*) FROM leads WHERE phone_status='Valid'"),
        "with_email": _count(cur, "SELECT COUNT(*) FROM leads WHERE email_status='Found'"),
        "hot_leads": _count(cur, "SELECT COUNT(*) FROM leads WHERE lead_quality='High'"),
        "interested": _count(cur, "SELECT COUNT(*) FROM leads WHERE status IN ('Interested','Replied')"),
        "new": _count(cur, "SELECT COUNT(*) FROM leads WHERE status='New'"),
        "contacted": _count(cur, "SELECT COUNT(*) FROM leads WHERE status IN ('Message Sent','Call Attempted','Replied','Interested','Follow Up Needed')"),
        "follow_up": _count(cur, "SELECT COUNT(*) FROM leads WHERE next_follow_up_at != '' AND next_follow_up_at <= ?", (today + " 23:59:59",)),
        "bad_websites": _count(cur, "SELECT COUNT(*) FROM leads WHERE website_status IN ('Needs Redesign','Unavailable')"),
        "no_social": _count(cur, "SELECT COUNT(*) FROM leads WHERE COALESCE(facebook_url,'')='' AND COALESCE(instagram_url,'')='' AND COALESCE(linkedin_url,'')='' AND COALESCE(tiktok_url,'')='' AND COALESCE(youtube_url,'')=''"),
        "conversion_rate": f"{round((converted / total) * 100, 1)}%" if total else "0%",
        "by_status": _group(cur, "status"),
        "by_city": _group(cur, "city"),
        "by_category": _group(cur, "category"),
        "by_website_status": _group(cur, "website_status"),
        "by_offer": _group(cur, "suggested_offer"),
    }
    conn.close()
    return stats


def whatsapp_number(phone_normalized: Optional[str], phone: Optional[str] = "") -> str:
    value = phone_normalized or phone or ""
    return re.sub(r"\D", "", value)


def suggested_message_for_lead(lead: Dict[str, Any]) -> str:
    name = lead.get("business_name") or "your business"
    category = (lead.get("category") or "business").lower()
    city = lead.get("city") or "your area"
    website_status = lead.get("website_status") or "No Website"
    offer = lead.get("suggested_offer") or recommend_offer(lead)
    rating = lead.get("rating")
    reviews = lead.get("reviews_count")
    proof = ""
    if rating and reviews:
        proof = f" You already have a good Google presence with {rating} rating and {reviews} reviews."
    if offer == "Website Redesign":
        problem = "your current website may need improvement for mobile users and customer conversion"
        solution = "a faster, cleaner, mobile-friendly website with clear contact and WhatsApp options"
    elif offer == "Social Media Setup":
        problem = "your online presence can be stronger with active social media pages"
        solution = "website/social media setup that helps customers contact you easily"
    elif website_status == "No Website" or not lead.get("website"):
        problem = "I could not find a professional website for your business"
        solution = "a clean, mobile-friendly website with contact/appointment options"
    else:
        problem = "your Google Business profile has room for improvement"
        solution = "Google profile optimization and local SEO improvements"
    return (
        f"Hello {name}, I found your {category} listing on Google in {city}.{proof} "
        f"I noticed that {problem}. We help local businesses with {solution}. "
        "Would you like me to share a simple improvement idea for your business?"
    )


def generate_proposal_text(lead: Dict[str, Any]) -> str:
    offer = lead.get("suggested_offer") or recommend_offer(lead)
    issues = lead.get("website_issues") or "No major website audit has been completed yet."
    domains = lead.get("domain_suggestions") or suggest_domains(lead.get("business_name"), lead.get("city"))
    return f"""Lead Improvement Proposal

Business: {lead.get('business_name') or ''}
City: {lead.get('city') or ''}
Category: {lead.get('category') or ''}
Phone: {lead.get('phone') or ''}
Email: {lead.get('email') or ''}
Website: {lead.get('website') or 'No website found'}
Google Rating: {lead.get('rating') or 'N/A'}
Reviews: {lead.get('reviews_count') or 'N/A'}
Lead Score: {lead.get('lead_score') or 0}/100
Recommended Offer: {offer}

Current Finding:
{issues}

Recommended Solution:
We recommend {offer.lower()} for {lead.get('business_name') or 'this business'}. The goal is to improve customer trust, mobile visibility, and direct inquiries through phone, WhatsApp, email, or appointment/contact forms.

Suggested Domain Options:
{domains}

Suggested Outreach Message:
{suggested_message_for_lead(lead)}
"""


def leads_for_export(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    where, params = _filters_to_where(filters)
    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT l.*, c.name AS campaign_name
        FROM leads l
        LEFT JOIN campaigns c ON c.id = l.campaign_id
        {where}
        ORDER BY l.lead_score DESC, l.updated_at DESC
        """,
        params,
    ).fetchall()
    conn.close()
    out = []
    for row in rows:
        d = dict(row)
        out.append({
            "Business Name": d.get("business_name"),
            "Phone": d.get("phone"),
            "Phone Status": d.get("phone_status"),
            "WhatsApp Link": f"https://wa.me/{whatsapp_number(d.get('phone_normalized'), d.get('phone'))}" if whatsapp_number(d.get('phone_normalized'), d.get('phone')) else "",
            "Email": d.get("email"),
            "Email Status": d.get("email_status"),
            "Address": d.get("address"),
            "City": d.get("city"),
            "Category": d.get("category"),
            "Website": d.get("website"),
            "Website Status": d.get("website_status"),
            "Website Quality Score": d.get("website_quality_score"),
            "Website Issues": d.get("website_issues"),
            "Facebook": d.get("facebook_url"),
            "Instagram": d.get("instagram_url"),
            "LinkedIn": d.get("linkedin_url"),
            "TikTok": d.get("tiktok_url"),
            "YouTube": d.get("youtube_url"),
            "Rating": d.get("rating"),
            "Reviews": d.get("reviews_count"),
            "Lead Score": d.get("lead_score"),
            "Lead Quality": d.get("lead_quality"),
            "Priority": d.get("priority"),
            "Status": d.get("status"),
            "Suggested Offer": d.get("suggested_offer"),
            "Campaign": d.get("campaign_name"),
            "Notes": d.get("notes"),
            "Last Contacted": d.get("last_contacted_at"),
            "Next Follow-up": d.get("next_follow_up_at"),
            "Google Maps Link": d.get("google_map_link"),
            "Domain Suggestions": d.get("domain_suggestions"),
            "Suggested Message": suggested_message_for_lead(d),
        })
    return out


def create_search_job(job_id: str, payload: Dict[str, Any]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO search_jobs
        (job_id, business_type, city, max_results, only_no_website, only_with_phone, status, message, filters_used, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'queued', 'Queued', ?, ?)
        """,
        (
            job_id,
            payload.get("business_type"),
            payload.get("city"),
            int(payload.get("max_results") or 30),
            1 if payload.get("only_no_website", True) else 0,
            1 if payload.get("only_with_phone", True) else 0,
            str(payload),
            now,
        ),
    )
    conn.commit()
    conn.close()


def update_search_job(job_id: str, **fields) -> None:
    if not fields:
        return
    allowed = {k for k in SEARCH_JOB_COLUMNS.keys() if k not in {"id", "job_id"}}
    payload = {k: v for k, v in fields.items() if k in allowed}
    if not payload:
        return
    conn = get_connection()
    set_clause = ", ".join([f"{k}=?" for k in payload])
    conn.execute(f"UPDATE search_jobs SET {set_clause} WHERE job_id=?", list(payload.values()) + [job_id])
    conn.commit()
    conn.close()


def list_search_jobs(limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM search_jobs ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_campaign(data: Dict[str, Any]) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO campaigns (name, description, category, city, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            normalize_text(data.get("name")),
            normalize_text(data.get("description")),
            normalize_text(data.get("category")),
            normalize_text(data.get("city")),
            data.get("status") or "Active",
            now,
            now,
        ),
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return int(cid)


def list_campaigns() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT c.*,
               COUNT(l.id) AS total_leads,
               SUM(CASE WHEN l.status IN ('Message Sent','Call Attempted','Replied','Interested','Follow Up Needed','Converted') THEN 1 ELSE 0 END) AS contacted,
               SUM(CASE WHEN l.status IN ('Interested','Replied') THEN 1 ELSE 0 END) AS interested,
               SUM(CASE WHEN l.status='Converted' THEN 1 ELSE 0 END) AS converted
        FROM campaigns c
        LEFT JOIN leads l ON l.campaign_id = c.id
        GROUP BY c.id
        ORDER BY c.updated_at DESC, c.id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_campaign(campaign_id: int, data: Dict[str, Any]) -> bool:
    allowed = {"name", "description", "category", "city", "status"}
    payload = {k: normalize_text(v) for k, v in data.items() if k in allowed}
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    cur = conn.cursor()
    set_clause = ", ".join([f"{k}=?" for k in payload])
    cur.execute(f"UPDATE campaigns SET {set_clause} WHERE id=?", list(payload.values()) + [campaign_id])
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok


def delete_campaign(campaign_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE leads SET campaign_id=NULL WHERE campaign_id=?", (campaign_id,))
    cur.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
    ok = cur.rowcount > 0
    conn.commit()
    conn.close()
    return ok
