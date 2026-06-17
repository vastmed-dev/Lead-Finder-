# Lead Finder CRM - Streamlit Version

This version is prepared for GitHub + Streamlit Community Cloud deployment.

## Main file
`streamlit_app.py`

## Deployment files
- `requirements.txt`
- `runtime.txt` uses Python 3.11
- `packages.txt` includes Linux packages needed by Playwright/Chromium
- `.streamlit/secrets.toml.example` includes 5 user login examples

## Streamlit Cloud Steps
1. Upload this folder to GitHub.
2. On Streamlit Cloud, create a new app.
3. Select `streamlit_app.py` as the main file.
4. In App Settings > Secrets, paste the users from `.streamlit/secrets.toml.example`.
5. Deploy.

## Login users
Default local fallback users are available in `streamlit_app.py`, but for live deployment use Streamlit Secrets.

## Important
Google Maps scraping uses Playwright. On Streamlit Cloud it must run headless and may need Chromium installation on first run.
