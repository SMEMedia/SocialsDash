# SME Media Social Performance Dashboard

A Streamlit dashboard for connected Meta and YouTube performance data, with direct profile links for Facebook, Instagram, LinkedIn, X, and TikTok.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The app reads credentials from Streamlit secrets. The existing `secrets.toml` can be used in this folder, or moved to `.streamlit/secrets.toml`. It is excluded from Git.

Expected sections and keys:

```toml
[meta]
page_access_token = "..."
user_access_token = "..."

[instagram]
access_token = "..."

[youtube]
client_id = "..."
client_secret = "..."
refresh_token = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

Meta Page Insights and post data require appropriate Page permissions. YouTube daily analytics require the YouTube Analytics API to be enabled and the refresh token to include an analytics read scope. If those permissions are absent, the dashboard still displays any available public/account totals and explains what could not load.
