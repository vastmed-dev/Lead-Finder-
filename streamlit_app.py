
import os
import sys
import uuid
import json
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

os.environ.setdefault("HEADLESS", "true")
os.environ.setdefault("DATABASE_PATH", "data/leads.db")
os.environ.setdefault("EXPORT_FOLDER", "exports")

from database import (
    CRM_STATUSES,
    PRESET_CATEGORIES,
    PRESET_CITIES,
    add_activity,
    apply_audit_to_lead,
    create_campaign,
    delete_lead,
    get_distinct_values,
    get_lead,
    get_stats,
    init_db,
    leads_for_export,
    list_activities,
    list_campaigns,
    list_leads,
    list_search_jobs,
    upsert_lead,
    update_lead,
    validate_and_normalize_phone,
    whatsapp_number,
)
from scraper import GoogleMapsScraper, ScraperConfig
from website_tools import audit_website

st.set_page_config(page_title="Lead Finder CRM", page_icon="📍", layout="wide")

Path("data").mkdir(exist_ok=True)
Path("exports").mkdir(exist_ok=True)
init_db()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_users():
    # Recommended: add users in Streamlit Cloud > App Settings > Secrets.
    # Format:
    # [users.admin]
    # password = "StrongPassword"
    # role = "Admin"
    if "users" in st.secrets:
        return {u: dict(v) for u, v in st.secrets["users"].items()}

    users_json = os.getenv("USERS_JSON", "").strip()
    if users_json:
        return json.loads(users_json)

    # Local fallback users. Change these in Streamlit secrets before public use.
    return {
        "admin": {"password": "VastAdmin#2026", "role": "Admin"},
        "manager": {"password": "LeadMgr#2026", "role": "Manager"},
        "sales1": {"password": "SalesOne#2026", "role": "Sales"},
        "sales2": {"password": "SalesTwo#2026", "role": "Sales"},
        "viewer": {"password": "ViewOnly#2026", "role": "Viewer"},
    }


USERS = load_users()


def check_password(username: str, password: str) -> bool:
    user = USERS.get(username)
    if not user:
        return False
    saved = str(user.get("password", ""))
    if saved.startswith("sha256:"):
        return saved.replace("sha256:", "") == hash_password(password)
    return saved == password


def login_screen():
    st.title("Lead Finder CRM Login")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
    if submitted:
        if check_password(username.strip(), password):
            st.session_state["logged_in"] = True
            st.session_state["username"] = username.strip()
            st.session_state["role"] = USERS[username.strip()].get("role", "")
            st.rerun()
        else:
            st.error("Invalid username or password.")


def require_login():
    if not st.session_state.get("logged_in"):
        login_screen()
        st.stop()


def install_playwright_browser_if_needed():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True, ""
    except Exception as exc:
        msg = str(exc)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0:
                return False, result.stderr or result.stdout or msg
            return True, "Chromium installed. Please run search again."
        except Exception as install_exc:
            return False, f"{msg}\n\nInstall error: {install_exc}"


def sidebar():
    st.sidebar.title("Lead Finder CRM")
    st.sidebar.caption(f"User: {st.session_state.get('username')} | {st.session_state.get('role')}")
    page = st.sidebar.radio(
        "Menu",
        ["Dashboard", "All Leads", "Follow Ups", "Campaigns", "Reports", "Settings"],
    )
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()
    return page


def show_stats():
    stats = get_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Leads", stats.get("total_leads", 0))
    c2.metric("No Website", stats.get("no_website", 0))
    c3.metric("Hot Leads", stats.get("hot_leads", 0))
    c4.metric("Follow Ups", stats.get("follow_ups", 0))
    c5.metric("Converted", stats.get("converted", 0))


def dashboard_page():
    st.title("Dashboard")
    show_stats()
    st.divider()

    st.subheader("Find Leads from Google Maps")
    with st.form("search_form"):
        col1, col2, col3 = st.columns(3)
        business_type = col1.text_input("Business Type", value="Dental Clinics")
        city = col2.text_input("City", value="Dallas")
        max_results = col3.number_input("Max Results", min_value=1, max_value=100, value=20)
        col4, col5, col6 = st.columns(3)
        only_no_website = col4.checkbox("Only without website", value=True)
        only_with_phone = col5.checkbox("Only with phone", value=True)
        auto_audit = col6.checkbox("Auto audit websites", value=False)
        submitted = st.form_submit_button("Start Search")

    if submitted:
        ok, browser_msg = install_playwright_browser_if_needed()
        if not ok:
            st.error("Playwright/Chromium issue. Add packages.txt and use Python 3.11. Error details:")
            st.code(browser_msg)
            st.stop()
        elif browser_msg:
            st.info(browser_msg)

        progress_bar = st.progress(0)
        status_box = st.empty()

        def progress(event):
            total = max(1, int(event.get("total") or max_results))
            current = min(total, int(event.get("current") or 0))
            progress_bar.progress(current / total)
            status_box.info(event.get("message", ""))

        try:
            scraper = GoogleMapsScraper(ScraperConfig(headless=True, slow_mo_ms=0))
            leads = scraper.search(
                business_type=business_type,
                city=city,
                max_results=max_results,
                only_no_website=only_no_website,
                only_with_phone=only_with_phone,
                progress=progress,
            )
            saved = 0
            for lead in leads:
                lead_id = upsert_lead(lead)
                saved += 1
                if auto_audit and lead.get("website"):
                    audit = audit_website(lead.get("website"), lead.get("business_name"))
                    apply_audit_to_lead(lead_id, audit)
            st.success(f"Completed. Found {len(leads)} leads and saved {saved}.")
            if leads:
                st.dataframe(pd.DataFrame(leads), use_container_width=True)
        except Exception as exc:
            st.error("Search failed.")
            st.code(str(exc))

    st.divider()
    st.subheader("Recent Search History")
    history = list_search_jobs(10)
    if history:
        st.dataframe(pd.DataFrame(history), use_container_width=True)
    else:
        st.info("No search history yet.")


def lead_filters():
    col1, col2, col3, col4 = st.columns(4)
    filters = {}
    q = col1.text_input("Search")
    if q:
        filters["q"] = q
    status = col2.selectbox("Status", [""] + CRM_STATUSES)
    if status:
        filters["status"] = status
    city = col3.selectbox("City", [""] + get_distinct_values("city"))
    if city:
        filters["city"] = city
    category = col4.selectbox("Category", [""] + get_distinct_values("category"))
    if category:
        filters["category"] = category
    return filters


def all_leads_page():
    st.title("All Leads")
    filters = lead_filters()
    data = list_leads(filters, page=1, per_page=500)
    leads = data.get("items", [])
    if leads:
        df = pd.DataFrame(leads)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), "leads.csv", "text/csv")
    else:
        st.info("No leads found.")

    st.subheader("Update Lead")
    lead_id = st.number_input("Lead ID", min_value=1, value=1)
    lead = get_lead(int(lead_id))
    if lead:
        with st.form("edit_lead"):
            col1, col2, col3 = st.columns(3)
            status = col1.selectbox("Status", CRM_STATUSES, index=CRM_STATUSES.index(lead.get("status")) if lead.get("status") in CRM_STATUSES else 0)
            priority = col2.selectbox("Priority", ["", "High", "Medium", "Low"], index=["", "High", "Medium", "Low"].index(lead.get("priority") or "") if (lead.get("priority") or "") in ["", "High", "Medium", "Low"] else 0)
            assigned_to = col3.text_input("Assigned To", value=lead.get("assigned_to") or "")
            notes = st.text_area("Notes", value=lead.get("notes") or "")
            next_follow = st.text_input("Next Follow Up Date", value=lead.get("next_follow_up_at") or "", placeholder="YYYY-MM-DD")
            if st.form_submit_button("Save"):
                update_lead(int(lead_id), status=status, priority=priority, assigned_to=assigned_to, notes=notes, next_follow_up_at=next_follow)
                add_activity(int(lead_id), "Update", f"Updated by {st.session_state.get('username')}")
                st.success("Lead updated.")
                st.rerun()

        c1, c2 = st.columns(2)
        if c1.button("Audit Website"):
            if lead.get("website"):
                audit = audit_website(lead.get("website"), lead.get("business_name"))
                apply_audit_to_lead(int(lead_id), audit)
                st.success("Website audit completed.")
                st.json(audit)
            else:
                st.warning("No website found for this lead.")
        if c2.button("Delete Lead"):
            delete_lead(int(lead_id))
            st.success("Lead deleted.")
            st.rerun()


def followups_page():
    st.title("Follow Ups")
    filters = {"status": "Follow Up Needed"}
    data = list_leads(filters, page=1, per_page=500)
    leads = data.get("items", [])
    if leads:
        st.dataframe(pd.DataFrame(leads), use_container_width=True, hide_index=True)
    else:
        st.info("No follow-up leads.")


def campaigns_page():
    st.title("Campaigns")
    with st.form("new_campaign"):
        col1, col2, col3 = st.columns(3)
        name = col1.text_input("Campaign Name")
        category = col2.text_input("Category")
        city = col3.text_input("City")
        description = st.text_area("Description")
        if st.form_submit_button("Create Campaign"):
            if name.strip():
                create_campaign({"name": name, "category": category, "city": city, "description": description})
                st.success("Campaign created.")
                st.rerun()
            else:
                st.error("Campaign name is required.")

    campaigns = list_campaigns()
    if campaigns:
        st.dataframe(pd.DataFrame(campaigns), use_container_width=True, hide_index=True)
    else:
        st.info("No campaigns yet.")


def reports_page():
    st.title("Reports")
    filters = lead_filters()
    rows = leads_for_export(filters)
    if not rows:
        st.info("No data available for export.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)
    st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), "lead_report.csv", "text/csv")
    excel_path = "exports/lead_report.xlsx"
    df.to_excel(excel_path, index=False)
    with open(excel_path, "rb") as f:
        st.download_button("Download Excel", f, "lead_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def settings_page():
    st.title("Settings")
    st.subheader("User Login Setup")
    st.write("For Streamlit Cloud, add users in App Settings > Secrets using this format:")
    st.code(
        """
[users.admin]
password = "VastAdmin#2026"
role = "Admin"

[users.manager]
password = "LeadMgr#2026"
role = "Manager"

[users.sales1]
password = "SalesOne#2026"
role = "Sales"

[users.sales2]
password = "SalesTwo#2026"
role = "Sales"

[users.viewer]
password = "ViewOnly#2026"
role = "Viewer"
""".strip(),
        language="toml",
    )
    st.subheader("Python Version")
    st.write("Use Python 3.11 for Streamlit Cloud. This avoids Playwright compatibility issues.")
    st.code("runtime.txt\npython-3.11", language="text")


require_login()
page = sidebar()

if page == "Dashboard":
    dashboard_page()
elif page == "All Leads":
    all_leads_page()
elif page == "Follow Ups":
    followups_page()
elif page == "Campaigns":
    campaigns_page()
elif page == "Reports":
    reports_page()
elif page == "Settings":
    settings_page()
