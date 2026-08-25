from __future__ import annotations

import html
import tomllib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


st.set_page_config(page_title="SME Media | Social Performance", page_icon="📈", layout="wide")

META_API = "https://graph.facebook.com/v23.0"
INSTAGRAM_API = "https://graph.instagram.com/v23.0"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2"

PROFILES = [
    ("Facebook", "facebook", "https://www.facebook.com/SMEMediaNews"),
    ("Instagram", "instagram", "https://www.instagram.com/smemedia/"),
    ("LinkedIn", "linkedin", "https://www.linkedin.com/showcase/sme-manufacturing-media/"),
    ("X", "x", "https://x.com/SMEMediaNews"),
    ("TikTok", "tiktok", "https://www.tiktok.com/@sme.media"),
]


class ApiError(RuntimeError):
    pass


def secret_section(name: str) -> dict[str, Any]:
    try:
        return dict(st.secrets[name])
    except (KeyError, FileNotFoundError):
        # Support the credential file already supplied at the project root.
        local_file = Path(__file__).with_name("secrets.toml")
        if local_file.is_file():
            with local_file.open("rb") as handle:
                return dict(tomllib.load(handle).get(name, {}))
        return {}


def request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, url, timeout=25, **kwargs)
        payload = response.json()
    except requests.RequestException as exc:
        raise ApiError(f"Could not reach the provider: {exc}") from exc
    except ValueError as exc:
        raise ApiError("The provider returned an unreadable response.") from exc
    if not response.ok:
        detail = payload.get("error", payload)
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("error_description") or str(detail)
        raise ApiError(str(detail))
    return payload


@st.cache_data(ttl=900, show_spinner=False)
def fetch_meta(start: str, end: str) -> dict[str, Any]:
    meta = secret_section("meta")
    instagram = secret_section("instagram")
    page_token = meta.get("page_access_token") or meta.get("user_access_token")
    if not page_token:
        raise ApiError("Meta page access token is missing.")

    page = request_json(
        "GET",
        f"{META_API}/me",
        params={"fields": "id,name,fan_count,followers_count,link,picture.type(large)", "access_token": page_token},
    )
    result: dict[str, Any] = {"page": page, "daily": [], "posts": [], "instagram": {}}

    # Insights availability depends on the permissions granted to the page token.
    # Query separately: Meta rejects the entire request if even one metric is retired.
    valid_metrics = [
        "page_views_total",
        "page_media_view",
        "page_post_engagements",
        "page_daily_follows",
        "page_daily_unfollows",
    ]
    by_day: dict[str, dict[str, Any]] = {}
    insight_errors: list[str] = []
    for metric_name in valid_metrics:
        try:
            insights = request_json(
                "GET",
                f"{META_API}/{page['id']}/insights",
                params={
                    "metric": metric_name,
                    "period": "day",
                    "since": start,
                    "until": end,
                    "access_token": page_token,
                },
            )
            for metric in insights.get("data", []):
                for point in metric.get("values", []):
                    day = point.get("end_time", "")[:10]
                    by_day.setdefault(day, {"date": day})[metric_name] = point.get("value", 0)
        except ApiError as exc:
            insight_errors.append(f"{metric_name}: {exc}")
    result["daily"] = sorted(by_day.values(), key=lambda row: row["date"])
    if insight_errors:
        result["insights_error"] = " · ".join(insight_errors)

    try:
        posts = request_json(
            "GET",
            f"{META_API}/{page['id']}/posts",
            params={
                "fields": "id,message,created_time,permalink_url,shares,likes.summary(true),comments.summary(true)",
                "since": start,
                "until": end,
                "limit": 50,
                "access_token": page_token,
            },
        )
        result["posts"] = posts.get("data", [])
    except ApiError as exc:
        result["posts_error"] = str(exc)

    ig_token = instagram.get("access_token")
    ig_error = None
    # Instagram Login tokens belong on graph.instagram.com, not graph.facebook.com.
    if ig_token:
        try:
            result["instagram"] = request_json(
                "GET",
                f"{INSTAGRAM_API}/me",
                params={"fields": "user_id,username,followers_count,media_count", "access_token": ig_token},
            )
        except ApiError as exc:
            ig_error = str(exc)
    # Fallback for Pages connected through Facebook Login.
    if not result["instagram"]:
        try:
            accounts = request_json(
                "GET",
                f"{META_API}/{page['id']}",
                params={"fields": "instagram_business_account", "access_token": page_token},
            )
            ig_id = accounts.get("instagram_business_account", {}).get("id")
            if ig_id:
                result["instagram"] = request_json(
                    "GET",
                    f"{META_API}/{ig_id}",
                    params={"fields": "id,username,name,followers_count,media_count,profile_picture_url", "access_token": page_token},
                )
        except ApiError as exc:
            ig_error = str(exc)
    if ig_error and not result["instagram"]:
        result["instagram_error"] = ig_error
    return result


@st.cache_data(ttl=900, show_spinner=False)
def fetch_youtube(start: str, end: str) -> dict[str, Any]:
    cfg = secret_section("youtube")
    missing = [key for key in ("client_id", "client_secret", "refresh_token") if not cfg.get(key)]
    if missing:
        raise ApiError(f"YouTube credential is missing: {', '.join(missing)}")
    token = request_json(
        "POST",
        cfg.get("token_uri", GOOGLE_TOKEN_URL),
        data={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "refresh_token": cfg["refresh_token"],
            "grant_type": "refresh_token",
        },
    )["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    channel_payload = request_json(
        "GET",
        f"{YOUTUBE_API}/channels",
        headers=headers,
        params={"part": "snippet,statistics", "mine": "true"},
    )
    channels = channel_payload.get("items", [])
    if not channels:
        raise ApiError("No YouTube channel is associated with these credentials.")
    channel = channels[0]
    result: dict[str, Any] = {"channel": channel, "daily": []}
    try:
        report = request_json(
            "GET",
            f"{YOUTUBE_ANALYTICS_API}/reports",
            headers=headers,
            params={
                "ids": "channel==MINE",
                "startDate": start,
                "endDate": end,
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,likes,comments,shares,subscribersGained,subscribersLost",
                "dimensions": "day",
                "sort": "day",
            },
        )
        columns = [column["name"] for column in report.get("columnHeaders", [])]
        result["daily"] = [dict(zip(columns, row)) for row in report.get("rows", [])]
    except ApiError as exc:
        result["analytics_error"] = str(exc)
    return result


def int_value(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def compact(value: Any) -> str:
    number = int_value(value)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:,}"


def metric_card(label: str, value: Any, note: str = "") -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(str(value))}</div><div class="metric-note">{html.escape(note)}</div></div>',
        unsafe_allow_html=True,
    )


def profile_links() -> str:
    icons = {
        "facebook": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#1877F2"/><path fill="white" d="M13.6 21v-8h2.7l.4-3h-3.1V8.1c0-.9.3-1.5 1.6-1.5h1.7V3.9c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3V10H7.4v3h2.8v8h3.4z"/></svg>',
        "instagram": '<svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#FFDC80"/><stop offset=".45" stop-color="#E1306C"/><stop offset="1" stop-color="#833AB4"/></linearGradient></defs><rect width="24" height="24" rx="6" fill="url(#ig)"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="white" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.2" fill="white"/></svg>',
        "linkedin": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="3" fill="#0A66C2"/><path fill="white" d="M6.2 8.3H3.4V20h2.8V8.3zM4.8 4A1.65 1.65 0 1 0 4.8 7.3 1.65 1.65 0 0 0 4.8 4zM20.6 13.3c0-3.5-1.9-5.2-4.4-5.2-2 0-3 1.1-3.5 1.9V8.3H10V20h2.8v-5.8c0-1.5.3-3 2.2-3 1.9 0 1.9 1.8 1.9 3.1V20h2.8l-.1-6.7z"/></svg>',
        "x": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="4" fill="#111"/><path fill="white" d="M5 4h3.7l4.1 5.5L17.6 4H19l-5.6 6.5L20 20h-3.7l-4.6-6.3L6.2 20H4.8l6.2-7.3L5 4zm2.2 1.1 9.6 13.8h1.9L9.1 5.1H7.2z"/></svg>',
        "tiktok": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="4" fill="#111"/><path fill="#25F4EE" d="M15 4v10.2a4.6 4.6 0 1 1-4-4.6v2.5a2.1 2.1 0 1 0 1.5 2V4H15z"/><path fill="#FE2C55" d="M16.3 4c.3 1.7 1.3 2.8 3 3.3v2.4a7 7 0 0 1-4.3-2V4h1.3z"/></svg>',
    }
    links = []
    for name, slug, url in PROFILES:
        links.append(
            f'<a class="social-link" href="{url}" target="_blank" title="Open {name}" rel="noopener">'
            f'{icons[slug]}<span>{name}</span></a>'
        )
    return '<div class="social-row">' + "".join(links) + "</div>"


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    .stApp { background: #f5f7fa; color: #172033; }
    [data-testid="stHeader"] { background: #f5f7fa; height: 3.5rem; }
    [data-testid="stToolbar"] { color: #172033; }
    .block-container { max-width: 1320px; padding-top: 4.75rem; padding-bottom: 4rem; }
    [data-testid="stSidebar"] { background: #111827; }
    [data-testid="stSidebar"] * { color: #f8fafc; }
    .eyebrow { color: #2563eb; font-size: .76rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
    .hero-title { font-size: clamp(2rem, 4vw, 3.5rem); font-weight: 700; letter-spacing: -.045em; margin: .2rem 0; }
    .hero-copy { color: #64748b; max-width: 700px; font-size: 1.05rem; }
    .metric-card { background: white; border: 1px solid #e5eaf1; border-radius: 16px; padding: 1.2rem 1.25rem; box-shadow: 0 8px 22px rgba(15,23,42,.04); min-height: 126px; }
    .metric-label { color: #64748b; font-size: .8rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; }
    .metric-value { color: #0f172a; font-size: 2rem; font-weight: 700; letter-spacing: -.04em; margin-top: .45rem; }
    .metric-note { color: #94a3b8; font-size: .78rem; min-height: 1rem; margin-top: .25rem; }
    .social-row { display:flex; gap:.75rem; flex-wrap:wrap; margin: 1rem 0 1.5rem; }
    .social-link { display:flex; align-items:center; gap:.55rem; background:white; border:1px solid #e2e8f0; color:#334155 !important; padding:.65rem .85rem; border-radius:999px; text-decoration:none !important; font-weight:600; font-size:.86rem; transition:.18s ease; }
    .social-link:hover { transform:translateY(-2px); border-color:#94a3b8; box-shadow:0 6px 14px rgba(15,23,42,.08); }
    .social-link svg { width:20px; height:20px; flex:0 0 20px; }
    .connection-note { background:#fff7ed; border:1px solid #fed7aa; border-radius:14px; color:#9a3412; padding:.9rem 1rem; margin:.5rem 0 1.5rem; }
    div[data-testid="stPlotlyChart"] { background:white; border:1px solid #e5eaf1; border-radius:16px; padding:.5rem; }
    .stTabs [data-baseweb="tab-list"] { gap:.35rem; border-bottom:1px solid #dbe3ed; }
    .stTabs [data-baseweb="tab"] { color:#475569 !important; background:#eef2f7; border-radius:9px 9px 0 0; padding:.65rem 1rem; }
    .stTabs [data-baseweb="tab"] p { color:#475569 !important; font-weight:600; }
    .stTabs [aria-selected="true"] { background:#ffffff !important; }
    .stTabs [aria-selected="true"] p { color:#2563eb !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="eyebrow">SME Media Intelligence</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">Social performance, at a glance.</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-copy">A live view of audience, reach, and engagement across SME Media’s connected channels.</div>', unsafe_allow_html=True)
st.markdown(profile_links(), unsafe_allow_html=True)
st.markdown(
    '<div class="connection-note"><b>Connection status:</b> Meta and YouTube are connected. '
    'LinkedIn, X, and TikTok are profile links only; API connections have not been configured.</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Dashboard controls")
    preset = st.selectbox("Reporting window", ["Last 7 days", "Last 30 days", "Last 90 days", "Custom"], index=1)
    today = date.today()
    days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}.get(preset, 30)
    if preset == "Custom":
        selected = st.date_input("Date range", value=(today - timedelta(days=30), today - timedelta(days=1)))
        if isinstance(selected, tuple) and len(selected) == 2:
            start_date, end_date = selected
        else:
            start_date, end_date = today - timedelta(days=30), today - timedelta(days=1)
    else:
        start_date, end_date = today - timedelta(days=days), today - timedelta(days=1)
    st.caption("Analytics data may lag by 24–72 hours.")
    if st.button("Refresh data", width="stretch"):
        st.cache_data.clear()

start, end = start_date.isoformat(), end_date.isoformat()
if start_date > end_date:
    st.error("The start date must be before the end date.")
    st.stop()

meta_data: dict[str, Any] | None = None
youtube_data: dict[str, Any] | None = None
meta_error = youtube_error = None
with st.spinner("Loading connected channels…"):
    try:
        meta_data = fetch_meta(start, end)
    except ApiError as exc:
        meta_error = str(exc)
    try:
        youtube_data = fetch_youtube(start, end)
    except ApiError as exc:
        youtube_error = str(exc)

st.markdown("### Network snapshot")
facebook_followers = (meta_data or {}).get("page", {}).get("followers_count") or (meta_data or {}).get("page", {}).get("fan_count")
instagram_followers = (meta_data or {}).get("instagram", {}).get("followers_count")
yt_stats = (youtube_data or {}).get("channel", {}).get("statistics", {})
cols = st.columns(4)
with cols[0]: metric_card("Facebook followers", compact(facebook_followers), "Current audience")
with cols[1]: metric_card("Instagram followers", compact(instagram_followers), "Current audience")
with cols[2]: metric_card("YouTube subscribers", compact(yt_stats.get("subscriberCount")), "Current audience")
with cols[3]: metric_card("YouTube lifetime views", compact(yt_stats.get("viewCount")), "All-time channel total")

if meta_error:
    st.warning(f"Meta data is unavailable: {meta_error}")
if youtube_error:
    st.warning(f"YouTube data is unavailable: {youtube_error}")

tab_overview, tab_meta, tab_youtube, tab_posts = st.tabs(["Overview", "Meta", "YouTube", "Content"])

with tab_overview:
    st.markdown("#### Performance trend")
    frames = []
    if meta_data and meta_data.get("daily"):
        frame = pd.DataFrame(meta_data["daily"])
        meta_trends = {
            "page_views_total": "Facebook page views",
            "page_media_view": "Facebook media views",
            "page_post_engagements": "Facebook engagements",
            "page_daily_follows": "Facebook follows",
        }
        for column, label in meta_trends.items():
            if column in frame:
                frames.append(frame[["date", column]].rename(columns={column: "value"}).assign(metric=label))
    if youtube_data and youtube_data.get("daily"):
        frame = pd.DataFrame(youtube_data["daily"])
        if "views" in frame:
            frames.append(frame[["day", "views"]].rename(columns={"day": "date", "views": "value"}).assign(metric="YouTube views"))
    if frames:
        trend = pd.concat(frames, ignore_index=True)
        trend["date"] = pd.to_datetime(trend["date"])
        fig = px.line(trend, x="date", y="value", color="metric", markers=True, color_discrete_sequence=["#2563eb", "#7c3aed", "#10b981", "#f59e0b", "#ef4444"], template="plotly_white")
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=25, b=20), legend_title_text="", xaxis_title="", yaxis_title="Daily activity", hovermode="x unified", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No daily trend data was returned for this reporting window. Check the API permission notes in the channel tabs.")

with tab_meta:
    st.markdown("#### Meta performance")
    daily = pd.DataFrame((meta_data or {}).get("daily", []))
    if not daily.empty:
        totals = {column: pd.to_numeric(daily[column], errors="coerce").fillna(0).sum() for column in daily.columns if column != "date"}
        a, b, c, d = st.columns(4)
        with a: metric_card("Page views", compact(totals.get("page_views_total")), f"{start} to {end}")
        with b: metric_card("Media views", compact(totals.get("page_media_view")), f"{start} to {end}")
        with c: metric_card("Post engagements", compact(totals.get("page_post_engagements")), f"{start} to {end}")
        with d: metric_card("New follows", compact(totals.get("page_daily_follows")), f"{start} to {end}")
        st.caption(f"Instagram media published all-time: {compact((meta_data or {}).get('instagram', {}).get('media_count'))}")
    elif meta_data:
        st.info("Page profile data connected successfully, but daily Page Insights were not returned.")
    if meta_data and meta_data.get("insights_error"):
        st.caption(f"Meta Insights API: {meta_data['insights_error']}")

with tab_youtube:
    st.markdown("#### YouTube performance")
    daily = pd.DataFrame((youtube_data or {}).get("daily", []))
    if not daily.empty:
        views = daily.get("views", pd.Series(dtype=float)).sum()
        minutes = daily.get("estimatedMinutesWatched", pd.Series(dtype=float)).sum()
        gained = daily.get("subscribersGained", pd.Series(dtype=float)).sum()
        lost = daily.get("subscribersLost", pd.Series(dtype=float)).sum()
        a, b, c, d = st.columns(4)
        with a: metric_card("Views", compact(views), f"{start} to {end}")
        with b: metric_card("Watch time", f"{minutes / 60:,.1f} hrs", "Estimated")
        with c: metric_card("Subscribers gained", compact(gained), "In reporting window")
        with d: metric_card("Net subscribers", f"{int(gained - lost):+,}", "Gained minus lost")
        engagement_cols = [column for column in ["likes", "comments", "shares"] if column in daily]
        if engagement_cols:
            chart = daily[["day", *engagement_cols]].melt("day", var_name="Engagement", value_name="Count")
            fig = px.bar(chart, x="day", y="Count", color="Engagement", barmode="group", color_discrete_sequence=["#ef4444", "#f59e0b", "#2563eb"], template="plotly_white")
            fig.update_layout(height=360, margin=dict(l=20, r=20, t=25, b=20), xaxis_title="", legend_title_text="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
            st.plotly_chart(fig, width="stretch")
    elif youtube_data:
        st.info("Channel totals connected successfully, but YouTube Analytics did not return daily data.")
    if youtube_data and youtube_data.get("analytics_error"):
        st.caption(f"YouTube Analytics API: {youtube_data['analytics_error']}")

with tab_posts:
    st.markdown("#### Recent Facebook posts")
    posts = (meta_data or {}).get("posts", [])
    if posts:
        rows = []
        for post in posts:
            rows.append({
                "Published": post.get("created_time", "")[:10],
                "Post": (post.get("message") or "(Media post)")[:140],
                "Likes": post.get("likes", {}).get("summary", {}).get("total_count", 0),
                "Comments": post.get("comments", {}).get("summary", {}).get("total_count", 0),
                "Shares": post.get("shares", {}).get("count", 0),
                "Link": post.get("permalink_url", ""),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={"Link": st.column_config.LinkColumn("Open")})
    else:
        st.info("No Facebook posts were returned for this reporting window.")
    if meta_data and meta_data.get("posts_error"):
        st.caption(f"Meta Posts API: {meta_data['posts_error']}")

st.caption(f"Reporting window: {start} through {end} · Data cached for 15 minutes · Last refreshed when this page loaded")
