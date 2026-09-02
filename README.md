# SME Media Social Performance Dashboard

This dashboard combines live Meta and YouTube information with saved LinkedIn and Facebook audience snapshots. It is designed for routine use in a web browser.

## Important links

- [Open the Social Dashboard](https://socialsdash.streamlit.app/)
- [SMEMedia repository](https://github.com/SMEMedia/SocialsDash)
- [Streamlit Community Cloud](https://share.streamlit.io/)

## Use the dashboard

1. Select the reporting window.
2. Review the channel tabs.
3. Select **Refresh data** once if live information appears stale.
4. Check the displayed update date for LinkedIn and Facebook audience-demographic sections.

Live Meta and YouTube responses are temporarily saved to keep the dashboard responsive. Platform reporting can lag by 24–72 hours. LinkedIn and Facebook audience demographics are dated snapshots and do not change when the reporting window changes.

## What is live and what is saved

| Section | Update behavior |
| --- | --- |
| Meta and Instagram performance | Live connection |
| YouTube performance | Live connection |
| Facebook audience demographics | Dated saved snapshot |
| LinkedIn analytics | Dated saved snapshot |
| X and TikTok | Profile links only |

## Reconnect YouTube

Use this process when the dashboard reports that YouTube authorization expired or was revoked:

1. Choose **Reconnect YouTube**.
2. Select **Start YouTube sign-in**, then **Continue to Google**.
3. Sign in with an account that manages the SME Media YouTube channel.
4. Approve the requested read-only access.
5. Follow the on-screen instructions to provide the renewed authorization to the Streamlit owner.
6. After it is saved, return to the dashboard and refresh once.

Never send the authorization information through email, chat, GitHub, tickets, or screenshots.

## Troubleshooting

### Meta or Instagram information is unavailable

- Confirm other dashboard sections still load.
- Refresh once.
- If the error remains, record whether it affects Facebook, Instagram, or both.
- Ask the Meta and Streamlit owners to confirm that the connection is active and still has access to the Page, Instagram account, Business portfolio, and developer app.

### YouTube information is unavailable

- Try **Reconnect YouTube** if the message says authorization expired or was revoked.
- Confirm the sign-in account manages the SME Media YouTube channel.
- If reconnection fails, send the visible message and time to the Google/YouTube and Streamlit owners.

### LinkedIn or Facebook audience charts look old

- Check the update date shown in the dashboard.
- These sections are saved snapshots, so this is expected until a new approved export is processed.
- Request a snapshot update from the assigned technical owner and provide the desired reporting period.

### A detailed metric is blank

- Some platforms do not return every metric for every content type.
- Confirm the date range includes the content.
- Compare the total metrics and any explanatory message before escalating.

### Numbers do not match a social platform

- Confirm the same date range, timezone, account, content type, and metric definition.
- Allow for the platform’s reporting delay.
- Record both values, filters, and comparison time before escalating.

### The dashboard will not open

- Use the live link above.
- Refresh the browser or try a private window.
- Check Streamlit Community Cloud for an app status message.
- Send a screenshot and approximate time to the Streamlit owner.

## Ongoing maintenance

- Record the update date whenever a new LinkedIn or Facebook audience snapshot is published.
- Keep Meta, Google/YouTube, Streamlit, and repository access assigned to current SME staff.
- Store credentials only in the approved secret-management location.
- Escalate snapshot replacement, credential, deployment, or code changes to the assigned technical owner.

