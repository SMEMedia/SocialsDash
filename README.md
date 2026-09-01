# SME Media Social Performance Dashboard

This is the handoff and operating guide for SME Media’s social media dashboard.

The dashboard combines live data from Meta and YouTube with manually exported LinkedIn and Facebook audience data. It is built with Streamlit and hosted from the `main` branch of the GitHub repository.

## Important links

- Source code: [github.com/myschne/SocialsDash](https://github.com/myschne/SocialsDash)
- Streamlit administration: [share.streamlit.io](https://share.streamlit.io/)
- Meta Business Suite: [business.facebook.com](https://business.facebook.com/)
- Meta developer apps: [developers.facebook.com/apps](https://developers.facebook.com/apps/)
- Google Cloud Console: [console.cloud.google.com](https://console.cloud.google.com/)

Add the public dashboard URL here after ownership is transferred:

> Dashboard URL: ______________________________

## What the dashboard contains

| Section | Source | Update method |
|---|---|---|
| Overview | Meta and YouTube | Live API connection |
| Meta performance | Facebook Page Insights | Live API connection |
| Instagram audience | Meta Instagram API | Live API connection; last-90-days reporting window |
| Facebook audience | Meta Business Suite export | Static snapshot uploaded August 25, 2026 |
| YouTube | YouTube Data and Analytics APIs | Live API connection |
| LinkedIn | LinkedIn analytics exports | Static snapshot uploaded August 25, 2026 |
| Facebook, Instagram, and YouTube content | Platform APIs | Live API connection |
| X and TikTok | Profile links only | No analytics connection |

Live API responses are cached for 15 minutes. Some platform analytics can lag by 24–72 hours.

## Routine use — no technical work required

1. Open the public dashboard link.
2. Select a reporting window in the left sidebar.
3. Use the tabs across the top to review each channel.
4. Select **Refresh data** if the displayed live information appears stale.
5. Remember that LinkedIn and Facebook audience demographics are dated static snapshots. Changing the reporting window does not change those sections.

The charts allow hover tooltips, but panning and zooming are intentionally disabled.

## Who needs access before the current owner leaves

At least two permanent SME employees should have access to every service below. Do not leave any service owned only by a departing employee.

### GitHub

The replacement owner needs administrator access to the `myschne/SocialsDash` repository. If the repository is under a personal GitHub account, transfer it to an SME-controlled GitHub organization or another approved company owner.

### Streamlit Community Cloud

The replacement owner needs access to the hosted app at [share.streamlit.io](https://share.streamlit.io/). Confirm that they can:

- Open the app settings.
- View deployment logs.
- Reboot or redeploy the app.
- Edit the app’s encrypted secrets.
- Connect the app to the GitHub repository.

### Meta

The replacement owner needs appropriate access to:

- The SME Media Facebook Page.
- The SME Media Instagram professional account.
- The associated Meta Business portfolio.
- The Meta developer app used to issue the access tokens.

They should be able to view insights and administer the developer app. The Facebook Page connection generally relies on Page access and `pages_read_engagement`/Page Insights permissions.

### Google and YouTube

The replacement owner needs access to:

- The SME Media YouTube channel.
- The Google Cloud project that owns the OAuth client.
- The YouTube Data API and YouTube Analytics API configuration.

### Credential handoff

Transfer credentials through an SME-approved password manager or secure credential system. Do not send tokens through email, Teams, Slack, tickets, or documents.

After ownership is transferred, rotate the Meta tokens, Instagram token, YouTube OAuth client secret, and YouTube refresh token. Then update the Streamlit secrets and test the dashboard.

## Secrets and security

The dashboard needs credentials for Meta, Instagram, and YouTube. These values must never be committed to GitHub.

There are two supported secret locations:

- Hosted app: Streamlit Community Cloud → app settings → **Secrets**
- Local computer: `secrets.toml` in this project folder, or `.streamlit/secrets.toml`

The local files are excluded by `.gitignore`. A safe placeholder file is available at `.streamlit/secrets.example.toml`.

The required structure is:

```toml
[meta]
app_id = "..."
app_secret = "..."
user_access_token = "..."
page_access_token = "..."

[instagram]
app_secret = "..."
access_token = "..."

[youtube]
client_id = "..."
client_secret = "..."
refresh_token = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

Do not add quotation marks around the entire secrets block in Streamlit. Paste it as TOML exactly as shown.

## How publishing works

The hosted Streamlit app reads the `main` branch of the GitHub repository. When a change is pushed to `main`, Streamlit normally redeploys automatically within a few minutes.

If a change does not appear:

1. Open the app in Streamlit Community Cloud.
2. Confirm the app points to the correct repository, branch (`main`), and entry file (`app.py`).
3. Open the app menu and reboot the app.
4. Review the deployment logs for a red error message.
5. Confirm all secrets are present and correctly formatted.

## Updating the static LinkedIn data

The LinkedIn tab is not connected to an API. Its current data covers August 24, 2025 through August 23, 2026 and was uploaded on August 25, 2026.

LinkedIn exports three workbooks:

- Followers
- Content
- Visitors

The dashboard reads normalized CSV files in `data/linkedin/`. The conversion utility is `scripts/prepare_linkedin_data.py`.

This update requires a technical owner or someone comfortable running Python:

1. Export the three reports from the LinkedIn Page administrator interface.
2. Save or convert them to `.xlsx` files.
3. Install the project requirements and `openpyxl` if it is not already available.
4. From this project folder, run:

```powershell
python scripts/prepare_linkedin_data.py `
  --followers "path\to\followers.xlsx" `
  --content "path\to\content.xlsx" `
  --visitors "path\to\visitors.xlsx" `
  --output "data\linkedin"
```

5. Update the `LINKEDIN_UPLOAD_DATE` value near the top of `app.py`.
6. Run and review the dashboard locally.
7. Commit the changed CSV files and `app.py`, then push them to `main`.

The LinkedIn CSV files contain analytics and post data. Confirm SME’s data-sharing policy before changing repository visibility or copying them elsewhere.

## Updating the static Facebook audience data

Meta no longer provides Facebook Page follower age, gender, country, or city metrics through the current Page Insights API. This dashboard therefore uses a static Business Suite export.

The current normalized snapshot is:

`data/meta/facebook_audience_2026-08-25.json`

Updating it requires a technical owner because the Business Suite CSV contains several differently shaped tables in one file. The owner should:

1. Export the Facebook audience report from Meta Business Suite.
2. Replace the normalized JSON snapshot with the new values.
3. Rename the file with the new export date.
4. Update `FACEBOOK_AUDIENCE_FILE` in `app.py` to the new filename.
5. Update the upload date stored inside the JSON file.
6. Test locally, commit, and push the change.

Treat the audience export as sensitive analytics data.

## Running the dashboard locally

Local setup is optional and intended for a technical owner.

Requirements:

- Python 3.11 or newer
- Internet access
- A local `secrets.toml` file with valid credentials

Commands:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Streamlit will display a local URL, usually `http://localhost:8501`.

## Troubleshooting

### The entire app will not load

- Check the Streamlit deployment logs.
- Confirm `app.py` is the configured entry file.
- Confirm all packages in `requirements.txt` installed successfully.
- Reboot the app from Streamlit Community Cloud.

### Meta or Instagram data is unavailable

- Confirm the Meta and Instagram secrets exist in Streamlit.
- Check whether the token expired or was revoked.
- Confirm the token owner still has access to the Facebook Page, Instagram account, Business portfolio, and Meta developer app.
- Generate a replacement token through the approved Meta administrator account and update Streamlit secrets.

### YouTube data is unavailable

- Confirm the YouTube secrets exist in Streamlit.
- Confirm the Google Cloud APIs are enabled.
- Check whether the OAuth refresh token was revoked.
- Reauthorize with an account that manages the SME Media YouTube channel.

### A static LinkedIn or Facebook chart looks old

This is expected until a new report is manually exported and committed. The upload date is shown in the dashboard.

### The app shows data but a detailed metric is missing

Platforms sometimes remove metrics or change permissions. The dashboard is designed to show available totals while displaying an explanatory message for an unavailable API section.

## Project file guide

| Path | Purpose |
|---|---|
| `app.py` | Complete Streamlit dashboard and API integrations |
| `requirements.txt` | Python packages installed by Streamlit |
| `.streamlit/config.toml` | Visual theme settings |
| `.streamlit/secrets.example.toml` | Safe credential template; contains no real secrets |
| `data/linkedin/` | Static LinkedIn analytics snapshot |
| `data/meta/` | Static Facebook audience snapshot |
| `scripts/prepare_linkedin_data.py` | Converts LinkedIn Excel exports to dashboard CSV files |
| `secrets.toml` | Local credentials; excluded from Git and never publishable |

## Change-control checklist

Before publishing any update:

1. Do not place credentials in code, CSV, JSON, screenshots, or documentation.
2. Run `python -m py_compile app.py`.
3. Run the dashboard locally and review every tab.
4. Confirm static data dates and labels are accurate.
5. Check `git status` and verify that `secrets.toml` is not listed.
6. Commit only the intended files.
7. Push to `main` and verify the hosted app redeploys successfully.

## Final ownership-transfer checklist

- [ ] Two SME employees can administer the GitHub repository.
- [ ] Two SME employees can administer the Streamlit app.
- [ ] Two SME employees can administer the Meta Business portfolio and developer app.
- [ ] Two SME employees can administer the Google Cloud project and YouTube channel.
- [ ] Streamlit secrets have been transferred through an approved secure system.
- [ ] Credentials have been rotated after the ownership change.
- [ ] The public dashboard URL has been added to this README.
- [ ] A replacement technical contact has successfully performed one test deployment.
- [ ] A future owner is assigned to refresh LinkedIn and Facebook audience exports.

## Support boundary

Routine dashboard use does not require technical knowledge. Credential rotation, API repairs, static-data replacement, and code changes should be handled by an assigned technical owner or approved external developer.
