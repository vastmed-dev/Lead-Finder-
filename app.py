# Lead Finder CRM Login Credentials
# Username: admin
# Password: admin123
# You can change these through .env using LOGIN_USERNAME and LOGIN_PASSWORD.

import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for

from database import (
    CONTACT_METHODS,
    CRM_STATUSES,
    EMAIL_STATUSES,
    LEAD_QUALITIES,
    PHONE_STATUSES,
    PRESET_CATEGORIES,
    PRESET_CITIES,
    PRIORITIES,
    SUGGESTED_OFFERS,
    WEBSITE_STATUSES,
    add_activity,
    apply_audit_to_lead,
    create_campaign,
    create_search_job,
    delete_campaign,
    delete_lead,
    generate_proposal_text,
    get_distinct_values,
    get_lead,
    get_stats,
    init_db,
    leads_for_export,
    list_activities,
    list_campaigns,
    list_leads,
    list_search_jobs,
    suggested_message_for_lead,
    update_campaign,
    update_lead,
    update_search_job,
    upsert_lead,
    validate_and_normalize_phone,
    whatsapp_number,
)
from scraper import GoogleMapsScraper, ScraperConfig
from website_tools import audit_website

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "local-lead-finder-secret")

# Fixed local login. Change these in .env if you want different credentials.
LOGIN_USERNAME = os.getenv("LOGIN_USERNAME", "admin")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "admin123")

EXPORT_FOLDER = Path(os.getenv("EXPORT_FOLDER", "exports"))
EXPORT_FOLDER.mkdir(exist_ok=True)

init_db()

JOBS = {}
JOBS_LOCK = threading.Lock()


def get_bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def set_job(job_id, **updates):
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)


def get_job(job_id):
    with JOBS_LOCK:
        return dict(JOBS.get(job_id, {}))


def safe_filename_part(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return value.strip("_") or "Leads"


def run_scrape_job(job_id, payload):
    business_type = payload.get("business_type", "").strip()
    city = payload.get("city", "").strip()
    max_results = int(payload.get("max_results") or 30)
    only_no_website = bool(payload.get("only_no_website", True))
    only_with_phone = bool(payload.get("only_with_phone", True))
    campaign_id = payload.get("campaign_id") or None
    auto_audit = bool(payload.get("auto_audit", False))
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def progress(event):
        set_job(
            job_id,
            step=event.get("step"),
            message=event.get("message"),
            current=event.get("current", 0),
            total=event.get("total", max_results),
        )
        update_search_job(job_id, message=event.get("message", ""))

    try:
        set_job(job_id, status="running", started_at=started_at, message="Starting scraper")
        update_search_job(job_id, status="running", started_at=started_at, message="Starting scraper")
        config = ScraperConfig(
            headless=get_bool(os.getenv("HEADLESS"), False),
            slow_mo_ms=int(os.getenv("SLOW_MO_MS", "40")),
        )
        scraper = GoogleMapsScraper(config=config)
        leads = scraper.search(
            business_type=business_type,
            city=city,
            max_results=max_results,
            only_no_website=only_no_website,
            only_with_phone=only_with_phone,
            progress=progress,
        )
        saved = 0
        failed = 0
        for index, lead in enumerate(leads, start=1):
            try:
                if campaign_id:
                    lead["campaign_id"] = campaign_id
                lead_id = upsert_lead(lead)
                saved += 1
                if auto_audit and lead.get("website"):
                    set_job(job_id, message=f"Auditing website {index}/{len(leads)}")
                    audit = audit_website(lead.get("website"), lead.get("business_name"))
                    apply_audit_to_lead(lead_id, audit)
            except Exception:
                failed += 1
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"Completed. Found {len(leads)} useful leads and saved {saved}."
        set_job(
            job_id,
            status="completed",
            step="completed",
            message=msg,
            total_found=len(leads),
            saved=saved,
            failed=failed,
            current=max_results,
            total=max_results,
            finished_at=finished_at,
        )
        update_search_job(
            job_id,
            status="completed",
            total_found=len(leads),
            saved_count=saved,
            failed_count=failed,
            message=msg,
            finished_at=finished_at,
        )
    except Exception as exc:
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_job(job_id, status="failed", step="failed", message=str(exc), error=str(exc), finished_at=finished_at)
        update_search_job(job_id, status="failed", message=str(exc), finished_at=finished_at)




def is_logged_in():
    return session.get("logged_in") is True


@app.before_request
def require_login():
    allowed_endpoints = {"login", "static"}
    if request.endpoint in allowed_endpoints:
        return None
    if not is_logged_in():
        if request.path.startswith("/api/") or request.path.startswith("/export/"):
            return jsonify({"error": "Login required"}), 401
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if is_logged_in():
        return redirect(url_for("dashboard"))

    error = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            return redirect(request.args.get("next") or url_for("dashboard"))
        error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/leads")
def leads_page():
    return render_template("leads.html")


@app.route("/follow-ups")
def followups_page():
    return render_template("followups.html")


@app.route("/campaigns")
def campaigns_page():
    return render_template("campaigns.html")


@app.route("/reports")
def reports_page():
    return render_template("reports.html")


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/options")
def api_options():
    return jsonify({
        "cities": get_distinct_values("city"),
        "categories": get_distinct_values("category"),
        "statuses": CRM_STATUSES,
        "contact_methods": CONTACT_METHODS,
        "priorities": PRIORITIES,
        "phone_statuses": PHONE_STATUSES,
        "email_statuses": EMAIL_STATUSES,
        "lead_qualities": LEAD_QUALITIES,
        "website_statuses": WEBSITE_STATUSES,
        "suggested_offers": SUGGESTED_OFFERS,
        "assigned_to": get_distinct_values("assigned_to"),
        "preset_categories": PRESET_CATEGORIES,
        "preset_cities": PRESET_CITIES,
        "campaigns": list_campaigns(),
    })


@app.route("/api/presets")
def api_presets():
    return jsonify({"categories": PRESET_CATEGORIES, "cities": PRESET_CITIES})


@app.route("/api/search-history")
def api_search_history():
    limit = int(request.args.get("limit", 8))
    return jsonify({"items": list_search_jobs(limit=limit)})


@app.route("/api/validate-phone", methods=["POST"])
def api_validate_phone():
    payload = request.get_json(force=True) or {}
    return jsonify(validate_and_normalize_phone(payload.get("phone")))


def lead_filters_from_request():
    return {
        "q": request.args.get("q", ""),
        "city": request.args.get("city", ""),
        "category": request.args.get("category", ""),
        "status": request.args.get("status", ""),
        "lead_quality": request.args.get("lead_quality", ""),
        "phone_status": request.args.get("phone_status", ""),
        "email_status": request.args.get("email_status", ""),
        "priority": request.args.get("priority", ""),
        "contact_method": request.args.get("contact_method", ""),
        "assigned_to": request.args.get("assigned_to", ""),
        "website_status": request.args.get("website_status", ""),
        "suggested_offer": request.args.get("suggested_offer", ""),
        "campaign_id": request.args.get("campaign_id", ""),
        "no_website": request.args.get("no_website", ""),
        "has_phone": request.args.get("has_phone", ""),
        "hot": request.args.get("hot", ""),
        "due_follow_up": request.args.get("due_follow_up", ""),
        "no_social": request.args.get("no_social", ""),
    }


@app.route("/api/leads")
def api_leads():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 25))
    return jsonify(list_leads(lead_filters_from_request(), page=page, per_page=per_page))


@app.route("/api/leads", methods=["POST"])
def api_create_lead():
    payload = request.get_json(force=True) or {}
    lead_id = upsert_lead(payload)
    return jsonify({"success": True, "id": lead_id})


@app.route("/api/leads/<int:lead_id>", methods=["GET"])
def api_get_lead(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    return jsonify(lead)


@app.route("/api/leads/<int:lead_id>", methods=["PATCH"])
def api_update_lead(lead_id):
    payload = request.get_json(force=True) or {}
    ok = update_lead(
        lead_id,
        status=payload.get("status"),
        notes=payload.get("notes"),
        contact_method=payload.get("contact_method"),
        assigned_to=payload.get("assigned_to"),
        priority=payload.get("priority"),
        last_contacted_at=payload.get("last_contacted_at"),
        next_follow_up_at=payload.get("next_follow_up_at"),
        campaign_id=payload.get("campaign_id") or None,
        suggested_offer=payload.get("suggested_offer"),
        email=payload.get("email"),
        website=payload.get("website"),
    )
    if not ok:
        return jsonify({"error": "Lead not found"}), 404
    return jsonify({"success": True})


@app.route("/api/leads/<int:lead_id>", methods=["DELETE"])
def api_delete_lead(lead_id):
    ok = delete_lead(lead_id)
    if not ok:
        return jsonify({"error": "Lead not found"}), 404
    return jsonify({"success": True})


@app.route("/api/leads/<int:lead_id>/audit", methods=["POST"])
def api_audit_lead(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    audit = audit_website(lead.get("website"), lead.get("business_name"))
    apply_audit_to_lead(lead_id, audit)
    return jsonify({"success": True, "audit": audit, "lead": get_lead(lead_id)})


@app.route("/api/leads/<int:lead_id>/activities")
def api_activities(lead_id):
    return jsonify({"items": list_activities(lead_id)})


@app.route("/api/leads/<int:lead_id>/activities", methods=["POST"])
def api_add_activity(lead_id):
    payload = request.get_json(force=True) or {}
    add_activity(lead_id, payload.get("activity_type") or "Note", payload.get("note") or "")
    return jsonify({"success": True, "items": list_activities(lead_id)})


@app.route("/api/leads/<int:lead_id>/proposal")
def api_proposal(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    return jsonify({"proposal": generate_proposal_text(lead)})


@app.route("/api/scrape/start", methods=["POST"])
def api_scrape_start():
    payload = request.get_json(force=True) or {}
    business_type = (payload.get("business_type") or "").strip()
    city = (payload.get("city") or "").strip()
    if not business_type or not city:
        return jsonify({"error": "Business type and city are required"}), 400
    job_id = str(uuid.uuid4())
    create_search_job(job_id, payload)
    set_job(job_id, status="queued", message="Queued", current=0, total=int(payload.get("max_results") or 30))
    thread = threading.Thread(target=run_scrape_job, args=(job_id, payload), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/scrape/job/<job_id>")
def api_scrape_job(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Live job not found. Check search history for saved jobs."}), 404
    return jsonify(job)


@app.route("/api/campaigns", methods=["GET"])
def api_campaigns():
    return jsonify({"items": list_campaigns()})


@app.route("/api/campaigns", methods=["POST"])
def api_create_campaign():
    payload = request.get_json(force=True) or {}
    if not payload.get("name"):
        return jsonify({"error": "Campaign name is required"}), 400
    cid = create_campaign(payload)
    return jsonify({"success": True, "id": cid, "items": list_campaigns()})


@app.route("/api/campaigns/<int:campaign_id>", methods=["PATCH"])
def api_update_campaign(campaign_id):
    ok = update_campaign(campaign_id, request.get_json(force=True) or {})
    if not ok:
        return jsonify({"error": "Campaign not found"}), 404
    return jsonify({"success": True, "items": list_campaigns()})


@app.route("/api/campaigns/<int:campaign_id>", methods=["DELETE"])
def api_delete_campaign(campaign_id):
    ok = delete_campaign(campaign_id)
    if not ok:
        return jsonify({"error": "Campaign not found"}), 404
    return jsonify({"success": True, "items": list_campaigns()})


def export_filename(ext: str, rows_count: int) -> Path:
    filters = lead_filters_from_request()
    category = safe_filename_part(filters.get("category") or "Leads")
    city = safe_filename_part(filters.get("city") or "All_Cities")
    lead_type = "No_Website_Leads" if filters.get("no_website") else "Lead_Export"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return EXPORT_FOLDER / f"{category}_{city}_{lead_type}_{rows_count}_{stamp}.{ext}"


@app.route("/export/excel")
def export_excel():
    rows = leads_for_export(lead_filters_from_request())
    df = pd.DataFrame(rows)
    filename = export_filename("xlsx", len(rows))
    df.to_excel(filename, index=False)
    return send_file(filename, as_attachment=True, download_name=filename.name)


@app.route("/export/csv")
def export_csv():
    rows = leads_for_export(lead_filters_from_request())
    df = pd.DataFrame(rows)
    filename = export_filename("csv", len(rows))
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    return send_file(filename, as_attachment=True, download_name=filename.name)


@app.route("/export/proposal/<int:lead_id>")
def export_proposal(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    text = generate_proposal_text(lead)
    filename = EXPORT_FOLDER / f"proposal_{safe_filename_part(lead.get('business_name'))}_{lead_id}.txt"
    filename.write_text(text, encoding="utf-8")
    return send_file(filename, as_attachment=True, download_name=filename.name)


@app.route("/export/html-report")
def export_html_report():
    rows = leads_for_export(lead_filters_from_request())
    stats = get_stats()
    html_rows = "".join(
        f"<tr><td>{r.get('Business Name','')}</td><td>{r.get('City','')}</td><td>{r.get('Phone','')}</td><td>{r.get('Website Status','')}</td><td>{r.get('Lead Score','')}</td><td>{r.get('Suggested Offer','')}</td></tr>"
        for r in rows[:300]
    )
    html = f"""
    <html><head><meta charset='utf-8'><title>Lead Finder CRM Report</title>
    <style>body{{font-family:Arial,sans-serif;padding:30px;color:#111827}}table{{width:100%;border-collapse:collapse}}td,th{{border:1px solid #ddd;padding:8px;font-size:12px}}th{{background:#f3f4f6}}.card{{display:inline-block;padding:14px 20px;margin:6px;border:1px solid #ddd;border-radius:12px}}</style>
    </head><body>
    <h1>Lead Finder CRM Report</h1>
    <div class='card'><b>Total Leads</b><br>{stats.get('total')}</div>
    <div class='card'><b>Hot Leads</b><br>{stats.get('hot_leads')}</div>
    <div class='card'><b>No Website</b><br>{stats.get('no_website')}</div>
    <div class='card'><b>Due Follow-ups</b><br>{stats.get('follow_up')}</div>
    <h2>Lead Summary</h2><table><thead><tr><th>Business</th><th>City</th><th>Phone</th><th>Website Status</th><th>Score</th><th>Offer</th></tr></thead><tbody>{html_rows}</tbody></table>
    </body></html>
    """
    filename = EXPORT_FOLDER / f"lead_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    filename.write_text(html, encoding="utf-8")
    return send_file(filename, as_attachment=True, download_name=filename.name)


@app.route("/api/whatsapp/<int:lead_id>")
def api_whatsapp(lead_id):
    lead = get_lead(lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    phone = whatsapp_number(lead.get("phone_normalized"), lead.get("phone"))
    message = suggested_message_for_lead(lead)
    return jsonify({
        "phone": phone,
        "message": message,
        "url": f"https://wa.me/{phone}?text={quote(message)}" if phone else "",
    })


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
