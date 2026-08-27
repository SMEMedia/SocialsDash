from __future__ import annotations

import html
import json
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
LINKEDIN_DATA_DIR = Path(__file__).with_name("data") / "linkedin"
LINKEDIN_UPLOAD_DATE = "August 25, 2026"
FACEBOOK_AUDIENCE_FILE = Path(__file__).with_name("data") / "meta" / "facebook_audience_2026-08-25.json"

PROFILES = [
    ("Facebook", "facebook", "https://www.facebook.com/SMEMediaNews"),
    ("Instagram", "instagram", "https://www.instagram.com/smemedia/"),
    ("LinkedIn", "linkedin", "https://www.linkedin.com/showcase/sme-manufacturing-media/"),
    ("X", "x", "https://x.com/SMEMediaNews"),
    ("TikTok", "tiktok", "https://www.tiktok.com/@sme.media"),
    ("YouTube", "youtube", "https://www.youtube.com/@SMEMedia"),
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
    result: dict[str, Any] = {"page": page, "daily": [], "posts": [], "instagram": {}, "instagram_media": [], "meta_audience": {}}

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
                "fields": "id,message,created_time,permalink_url,shares,attachments{media_type,type,url},likes.summary(true),comments.summary(true)",
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
    elif ig_token:
        try:
            media = request_json(
                "GET",
                f"{INSTAGRAM_API}/me/media",
                params={
                    "fields": "id,caption,media_type,permalink,timestamp,like_count,comments_count",
                    "limit": 50,
                    "access_token": ig_token,
                },
            )
            result["instagram_media"] = [
                item for item in media.get("data", [])
                if start <= item.get("timestamp", "")[:10] <= end
            ]
        except ApiError as exc:
            result["instagram_media_error"] = str(exc)
    if ig_token:
        audience_errors: list[str] = []
        for breakdown in ("age,gender", "country", "city"):
            try:
                audience = request_json(
                    "GET",
                    f"{INSTAGRAM_API}/me/insights",
                    params={
                        "metric": "follower_demographics",
                        "period": "lifetime",
                        "metric_type": "total_value",
                        "breakdown": breakdown,
                        "timeframe": "last_90_days",
                        "access_token": ig_token,
                    },
                )
                data = audience.get("data", [])
                breakdowns = data[0].get("total_value", {}).get("breakdowns", []) if data else []
                result["meta_audience"][breakdown] = breakdowns[0].get("results", []) if breakdowns else []
            except ApiError as exc:
                audience_errors.append(f"{breakdown}: {exc}")
        if audience_errors:
            result["meta_audience_error"] = " · ".join(audience_errors)
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
        params={"part": "snippet,statistics,contentDetails", "mine": "true"},
    )
    channels = channel_payload.get("items", [])
    if not channels:
        raise ApiError("No YouTube channel is associated with these credentials.")
    channel = channels[0]
    result: dict[str, Any] = {"channel": channel, "daily": [], "videos": []}
    try:
        uploads_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if uploads_id:
            playlist = request_json(
                "GET",
                f"{YOUTUBE_API}/playlistItems",
                headers=headers,
                params={"part": "snippet,contentDetails", "playlistId": uploads_id, "maxResults": 50},
            )
            recent_items = [
                item for item in playlist.get("items", [])
                if start <= item.get("contentDetails", {}).get("videoPublishedAt", "")[:10] <= end
            ]
            video_ids = [item.get("contentDetails", {}).get("videoId") for item in recent_items]
            video_ids = [video_id for video_id in video_ids if video_id]
            if video_ids:
                videos = request_json(
                    "GET",
                    f"{YOUTUBE_API}/videos",
                    headers=headers,
                    params={"part": "snippet,statistics", "id": ",".join(video_ids)},
                )
                result["videos"] = videos.get("items", [])
    except ApiError as exc:
        result["videos_error"] = str(exc)
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


@st.cache_data(show_spinner=False)
def linkedin_csv(name: str) -> pd.DataFrame:
    path = LINKEDIN_DATA_DIR / f"{name}.csv"
    return pd.read_csv(path) if path.is_file() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def facebook_audience_snapshot() -> dict[str, Any]:
    if not FACEBOOK_AUDIENCE_FILE.is_file():
        return {}
    with FACEBOOK_AUDIENCE_FILE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def facebook_post_type(post: dict[str, Any]) -> str:
    """Map Graph attachment metadata into dashboard-friendly content types."""
    permalink = str(post.get("permalink_url", "")).lower()
    message = str(post.get("message", "")).lower()
    attachments = post.get("attachments", {}).get("data", [])
    attachment = attachments[0] if attachments else {}
    media_type = str(attachment.get("media_type", "")).lower()
    attachment_type = str(attachment.get("type", "")).lower()
    attachment_url = str(attachment.get("url", "")).lower()
    combined = " ".join((permalink, media_type, attachment_type, attachment_url))

    if "/reel/" in permalink or "/reels/" in permalink or "reel" in combined:
        return "Reel"
    if "live" in combined or (" live" in message and "video" in combined):
        return "Live"
    if "photo" in combined or "album" in combined or "image" in combined:
        return "Photo"
    if "link" in combined or "share" in attachment_type:
        return "Link"
    # Standard Facebook video posts are grouped with Reels in the requested
    # five-type view unless Graph marks them as Live.
    if "video" in combined:
        return "Reel"
    return "Text"


def metric_card(label: str, value: Any, note: str = "") -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(str(value))}</div><div class="metric-note">{html.escape(note)}</div></div>',
        unsafe_allow_html=True,
    )


def show_chart(figure: Any) -> None:
    """Render a Plotly chart with pan and zoom interactions disabled."""
    figure.update_xaxes(fixedrange=True)
    figure.update_yaxes(fixedrange=True)
    figure.update_layout(dragmode=False)
    st.plotly_chart(
        figure,
        width="stretch",
        config={"scrollZoom": False, "displayModeBar": False, "doubleClick": False},
    )


def profile_links() -> str:
    icons = {
        "facebook": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#1877F2"/><path fill="white" d="M13.6 21v-8h2.7l.4-3h-3.1V8.1c0-.9.3-1.5 1.6-1.5h1.7V3.9c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3V10H7.4v3h2.8v8h3.4z"/></svg>',
        "instagram": '<svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#FFDC80"/><stop offset=".45" stop-color="#E1306C"/><stop offset="1" stop-color="#833AB4"/></linearGradient></defs><rect width="24" height="24" rx="6" fill="url(#ig)"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="white" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1.2" fill="white"/></svg>',
        "linkedin": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="3" fill="#0A66C2"/><path fill="white" d="M6.2 8.3H3.4V20h2.8V8.3zM4.8 4A1.65 1.65 0 1 0 4.8 7.3 1.65 1.65 0 0 0 4.8 4zM20.6 13.3c0-3.5-1.9-5.2-4.4-5.2-2 0-3 1.1-3.5 1.9V8.3H10V20h2.8v-5.8c0-1.5.3-3 2.2-3 1.9 0 1.9 1.8 1.9 3.1V20h2.8l-.1-6.7z"/></svg>',
        "x": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="4" fill="#111"/><path fill="white" d="M5 4h3.7l4.1 5.5L17.6 4H19l-5.6 6.5L20 20h-3.7l-4.6-6.3L6.2 20H4.8l6.2-7.3L5 4zm2.2 1.1 9.6 13.8h1.9L9.1 5.1H7.2z"/></svg>',
        "tiktok": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect width="24" height="24" rx="4" fill="#111"/><path fill="#25F4EE" d="M15 4v10.2a4.6 4.6 0 1 1-4-4.6v2.5a2.1 2.1 0 1 0 1.5 2V4H15z"/><path fill="#FE2C55" d="M16.3 4c.3 1.7 1.3 2.8 3 3.3v2.4a7 7 0 0 1-4.3-2V4h1.3z"/></svg>',
        "youtube": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1" y="4" width="22" height="16" rx="5" fill="#FF0000"/><path fill="white" d="m10 8.5 6 3.5-6 3.5v-7z"/></svg>',
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
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] [data-baseweb="input"] > div,
    [data-testid="stSidebar"] [data-baseweb="base-input"],
    [data-testid="stSidebar"] button[kind="secondary"] { background:#f8fafc !important; }
    [data-testid="stSidebar"] [data-baseweb="select"] *,
    [data-testid="stSidebar"] [data-baseweb="input"] *,
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] button[kind="secondary"] * {
        color:#172033 !important; -webkit-text-fill-color:#172033 !important; opacity:1 !important;
    }
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
    [data-baseweb="tab-list"] { gap:.35rem !important; border-bottom:1px solid #dbe3ed !important; }
    [data-baseweb="tab-list"] [role="tab"] {
        color:#334155 !important; background:#e8edf4 !important; opacity:1 !important;
        border-radius:9px 9px 0 0 !important; padding:.65rem 1rem !important;
    }
    [data-baseweb="tab-list"] [role="tab"] * {
        color:#334155 !important; opacity:1 !important; font-weight:700 !important;
        -webkit-text-fill-color:#334155 !important;
    }
    [data-baseweb="tab-list"] [role="tab"][aria-selected="true"] { background:#ffffff !important; }
    [data-baseweb="tab-list"] [role="tab"][aria-selected="true"] * {
        color:#2563eb !important; -webkit-text-fill-color:#2563eb !important;
    }
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

tab_overview, tab_meta, tab_youtube, tab_linkedin, tab_posts = st.tabs(["Overview", "Meta", "YouTube", "LinkedIn", "Content"])

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
        show_chart(fig)
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
        meta_chart_columns = {
            "page_views_total": "Page views",
            "page_media_view": "Media views",
            "page_post_engagements": "Post engagements",
        }
        available_meta = [column for column in meta_chart_columns if column in daily]
        if available_meta:
            meta_chart = daily[["date", *available_meta]].copy()
            meta_chart["date"] = pd.to_datetime(meta_chart["date"])
            for column in available_meta:
                meta_chart[column] = pd.to_numeric(meta_chart[column], errors="coerce").fillna(0).clip(lower=0)
            meta_chart = meta_chart.rename(columns=meta_chart_columns).melt("date", var_name="Metric", value_name="Daily total")
            meta_fig = px.line(
                meta_chart,
                x="date",
                y="Daily total",
                color="Metric",
                markers=True,
                template="plotly_white",
                color_discrete_sequence=["#1877f2", "#7c3aed", "#10b981"],
            )
            meta_fig.update_traces(line=dict(width=2.5), marker=dict(size=5))
            meta_fig.update_layout(
                title="Daily Meta activity",
                height=390,
                margin=dict(l=20, r=20, t=55, b=20),
                xaxis_title="",
                legend_title_text="",
                hovermode="x unified",
                paper_bgcolor="white",
                plot_bgcolor="white",
                font_color="#334155",
            )
            show_chart(meta_fig)
    elif meta_data:
        st.info("Page profile data connected successfully, but daily Page Insights were not returned.")
    facebook_audience = facebook_audience_snapshot()
    if facebook_audience:
        st.markdown("#### Meta audience")
        st.markdown(
            f'<div class="connection-note"><b>Static Facebook audience snapshot:</b> Uploaded {facebook_audience.get("uploaded_date", "August 25, 2026")}. '
            'Facebook audience demographics do not refresh automatically.</div>',
            unsafe_allow_html=True,
        )
        facebook_age = pd.DataFrame(facebook_audience.get("age_gender", []))
        if not facebook_age.empty:
            facebook_age = facebook_age.rename(columns={"age": "Age", "men": "Men", "women": "Women"})
            facebook_age_chart = facebook_age.melt("Age", value_vars=["Men", "Women"], var_name="Gender", value_name="Percent")
            facebook_age_chart["Share"] = facebook_age_chart["Percent"] / 100
            fb_age_fig = px.bar(
                facebook_age_chart,
                x="Age",
                y="Share",
                color="Gender",
                barmode="group",
                category_orders={"Age": ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]},
                color_discrete_map={"Men": "#93c5fd", "Women": "#2563eb"},
                template="plotly_white",
                hover_data={"Percent": ":.1f", "Share": False},
            )
            fb_age_fig.update_layout(title="Facebook follower age and gender", height=390, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", yaxis_title="Share of followers", yaxis_tickformat=".0%", legend_title_text="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
            show_chart(fb_age_fig)

        fb_geo_left, fb_geo_right = st.columns(2)
        for column, key, label in [(fb_geo_left, "countries", "Country"), (fb_geo_right, "cities", "City")]:
            with column:
                geo = pd.DataFrame(facebook_audience.get(key, []))
                if not geo.empty:
                    geo = geo.rename(columns={"name": label, "share": "Percent"}).sort_values("Percent")
                    geo["Share"] = geo["Percent"] / 100
                    fb_geo_fig = px.bar(geo, x="Share", y=label, orientation="h", text="Percent", template="plotly_white", color_discrete_sequence=["#0f766e"])
                    fb_geo_fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                    fb_geo_fig.update_layout(title=f"Facebook top {key}", height=410, margin=dict(l=20, r=45, t=55, b=20), xaxis_title="Share of followers", xaxis_tickformat=".0%", yaxis_title="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
                    show_chart(fb_geo_fig)

        follows = pd.DataFrame(facebook_audience.get("follows", []))
        if not follows.empty:
            follows["date"] = pd.to_datetime(follows["date"])
            follows_fig = px.bar(follows, x="date", y="value", template="plotly_white", color_discrete_sequence=["#1877f2"], labels={"date": "", "value": "New follows"})
            follows_fig.update_layout(title="Facebook daily follows in the export", height=320, margin=dict(l=20, r=20, t=55, b=20), paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
            show_chart(follows_fig)

    audience = (meta_data or {}).get("meta_audience", {})
    if audience:
        st.markdown("#### Instagram audience")
        st.caption("Live Instagram follower demographics from Meta · Meta reporting window: last 90 days")
        age_gender_rows = []
        gender_names = {"F": "Women", "M": "Men", "U": "Unspecified"}
        for item in audience.get("age,gender", []):
            dimensions = item.get("dimension_values", [])
            if len(dimensions) >= 2:
                age_gender_rows.append({"Age": dimensions[0], "Gender": gender_names.get(dimensions[1], dimensions[1]), "Followers": int_value(item.get("value"))})
        if age_gender_rows:
            age_frame = pd.DataFrame(age_gender_rows)
            reported_total = age_frame["Followers"].sum()
            age_frame["Share"] = age_frame["Followers"] / reported_total if reported_total else 0
            age_order = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
            age_fig = px.bar(
                age_frame,
                x="Age",
                y="Share",
                color="Gender",
                barmode="group",
                category_orders={"Age": age_order, "Gender": ["Men", "Women", "Unspecified"]},
                color_discrete_map={"Men": "#60a5fa", "Women": "#ec4899", "Unspecified": "#94a3b8"},
                template="plotly_white",
                hover_data={"Followers": True, "Share": ":.1%"},
            )
            age_fig.update_layout(title="Age and gender", height=390, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", yaxis_title="Share of reported followers", yaxis_tickformat=".0%", legend_title_text="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
            show_chart(age_fig)

        country_names = {
            "US": "United States", "IN": "India", "PR": "Puerto Rico", "CN": "China", "TR": "Türkiye",
            "PK": "Pakistan", "GB": "United Kingdom", "CA": "Canada", "MX": "Mexico", "BR": "Brazil",
            "DE": "Germany", "FR": "France", "AU": "Australia", "ZA": "South Africa", "IT": "Italy",
            "ID": "Indonesia", "CH": "Switzerland", "TN": "Tunisia", "CL": "Chile", "PE": "Peru",
        }

        def demographic_frame(items: list[dict[str, Any]], dimension: str) -> pd.DataFrame:
            rows = []
            for item in items:
                values = item.get("dimension_values", [])
                if values:
                    label = values[0]
                    if dimension == "Country":
                        label = country_names.get(label, label)
                    rows.append({dimension: label, "Followers": int_value(item.get("value"))})
            frame = pd.DataFrame(rows)
            if not frame.empty:
                total = frame["Followers"].sum()
                frame["Share"] = frame["Followers"] / total if total else 0
            return frame

        country_frame = demographic_frame(audience.get("country", []), "Country")
        city_frame = demographic_frame(audience.get("city", []), "City")
        geo_left, geo_right = st.columns(2)
        for column, frame, dimension, title in [
            (geo_left, country_frame, "Country", "Top countries"),
            (geo_right, city_frame, "City", "Top cities"),
        ]:
            with column:
                if not frame.empty:
                    top = frame.nlargest(10, "Followers").sort_values("Followers")
                    geo_fig = px.bar(top, x="Share", y=dimension, orientation="h", text="Followers", template="plotly_white", color_discrete_sequence=["#0f766e"])
                    geo_fig.update_layout(title=title, height=390, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="Share of reported followers", xaxis_tickformat=".0%", yaxis_title="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
                    show_chart(geo_fig)
        st.info("Facebook Page follower demographics are no longer returned by the current Meta Page Insights API. The Instagram charts in this section remain live; the Facebook charts use the dated export above.")
    if meta_data and meta_data.get("meta_audience_error"):
        st.caption(f"Meta Audience API: {meta_data['meta_audience_error']}")
    if meta_data and meta_data.get("insights_error"):
        st.caption(f"Meta Insights API: {meta_data['insights_error']}")

with tab_youtube:
    st.markdown("#### YouTube performance")
    daily = pd.DataFrame((youtube_data or {}).get("daily", []))
    if not daily.empty:
        daily["day"] = pd.to_datetime(daily["day"])
        numeric_columns = ["views", "estimatedMinutesWatched", "likes", "comments", "shares", "subscribersGained", "subscribersLost"]
        for column in numeric_columns:
            if column in daily:
                daily[column] = pd.to_numeric(daily[column], errors="coerce").fillna(0)
        views = daily.get("views", pd.Series(dtype=float)).sum()
        minutes = daily.get("estimatedMinutesWatched", pd.Series(dtype=float)).sum()
        gained = daily.get("subscribersGained", pd.Series(dtype=float)).sum()
        lost = daily.get("subscribersLost", pd.Series(dtype=float)).sum()
        a, b, c, d = st.columns(4)
        with a: metric_card("Views", compact(views), f"{start} to {end}")
        with b: metric_card("Watch time", f"{minutes / 60:,.1f} hrs", "Estimated")
        with c: metric_card("Subscribers gained", compact(gained), "In reporting window")
        with d: metric_card("Net subscribers", f"{int(gained - lost):+,}", "Gained minus lost")
        if "views" in daily:
            daily["7-day average"] = daily["views"].rolling(7, min_periods=1).mean()
            views_fig = px.area(
                daily,
                x="day",
                y="views",
                template="plotly_white",
                labels={"day": "", "views": "Daily views"},
                color_discrete_sequence=["#bfdbfe"],
            )
            views_fig.update_traces(name="Daily views", line=dict(color="#60a5fa", width=1.5), fillcolor="rgba(96,165,250,.22)")
            views_fig.add_scatter(
                x=daily["day"],
                y=daily["7-day average"],
                mode="lines",
                name="7-day average",
                line=dict(color="#dc2626", width=3),
            )
            views_fig.update_layout(
                title="Views over time",
                height=400,
                margin=dict(l=20, r=20, t=55, b=20),
                legend_title_text="",
                hovermode="x unified",
                paper_bgcolor="white",
                plot_bgcolor="white",
                font_color="#334155",
            )
            show_chart(views_fig)

        chart_left, chart_right = st.columns(2)
        engagement_cols = [column for column in ["likes", "comments", "shares"] if column in daily]
        if engagement_cols:
            # YouTube reports net likes, which can be negative when likes are removed.
            # For an activity chart, show new positive interactions only.
            engagement = daily[["day", *engagement_cols]].copy()
            engagement[engagement_cols] = engagement[engagement_cols].clip(lower=0)
            chart = engagement.melt("day", var_name="Engagement", value_name="Count")
            fig = px.bar(chart, x="day", y="Count", color="Engagement", barmode="stack", color_discrete_sequence=["#ef4444", "#f59e0b", "#2563eb"], template="plotly_white")
            fig.update_layout(title="Positive engagement", height=350, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", legend_title_text="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
            with chart_left:
                show_chart(fig)
        if "subscribersGained" in daily and "subscribersLost" in daily:
            subscriber_chart = daily[["day", "subscribersGained", "subscribersLost"]].copy()
            subscriber_chart["Net subscribers"] = subscriber_chart["subscribersGained"] - subscriber_chart["subscribersLost"]
            subscriber_chart["Direction"] = subscriber_chart["Net subscribers"].apply(lambda value: "Gained" if value >= 0 else "Lost")
            sub_fig = px.bar(
                subscriber_chart,
                x="day",
                y="Net subscribers",
                color="Direction",
                color_discrete_map={"Gained": "#10b981", "Lost": "#ef4444"},
                template="plotly_white",
            )
            sub_fig.update_layout(title="Daily subscriber change", height=350, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", legend_title_text="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
            with chart_right:
                show_chart(sub_fig)
    elif youtube_data:
        st.info("Channel totals connected successfully, but YouTube Analytics did not return daily data.")
    if youtube_data and youtube_data.get("analytics_error"):
        st.caption(f"YouTube Analytics API: {youtube_data['analytics_error']}")

with tab_linkedin:
    st.markdown("#### LinkedIn performance")
    st.markdown(
        f'<div class="connection-note"><b>Static LinkedIn snapshot:</b> These files were uploaded on {LINKEDIN_UPLOAD_DATE}. '
        'LinkedIn is not API-connected, so this tab does not refresh automatically or follow the dashboard date control.</div>',
        unsafe_allow_html=True,
    )
    li_content = linkedin_csv("content_metrics")
    li_followers = linkedin_csv("followers_new_followers")
    li_visitors = linkedin_csv("visitors_visitor_metrics")
    li_posts = linkedin_csv("content_all_posts")

    if not li_content.empty and not li_followers.empty and not li_visitors.empty:
        for frame in (li_content, li_followers, li_visitors):
            frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        content_impressions = pd.to_numeric(li_content.get("Impressions (total)"), errors="coerce").fillna(0).sum()
        content_clicks = pd.to_numeric(li_content.get("Clicks (total)"), errors="coerce").fillna(0).sum()
        follower_gains = pd.to_numeric(li_followers.get("Total followers"), errors="coerce").fillna(0).sum()
        page_views = pd.to_numeric(li_visitors.get("Total page views (total)"), errors="coerce").fillna(0).sum()
        unique_visitors = pd.to_numeric(li_visitors.get("Total unique visitors (total)"), errors="coerce").fillna(0).sum()
        total_engagements = sum(
            pd.to_numeric(li_content.get(column), errors="coerce").fillna(0).sum()
            for column in ["Clicks (total)", "Reactions (total)", "Comments (total)", "Reposts (total)"]
        )
        engagement_rate = total_engagements / content_impressions if content_impressions else 0

        li_kpis = st.columns(5)
        with li_kpis[0]: metric_card("Impressions", compact(content_impressions), "Static export total")
        with li_kpis[1]: metric_card("Clicks", compact(content_clicks), "Static export total")
        with li_kpis[2]: metric_card("Engagement rate", f"{engagement_rate:.1%}", "Weighted total")
        with li_kpis[3]: metric_card("Followers gained", compact(follower_gains), "During export period")
        with li_kpis[4]: metric_card("Unique visitors", compact(unique_visitors), f"{compact(page_views)} page views")

        li_content = li_content.sort_values("Date")
        li_trend = li_content[["Date", "Impressions (total)", "Clicks (total)"]].copy()
        li_trend["Impressions"] = pd.to_numeric(li_trend["Impressions (total)"], errors="coerce").fillna(0)
        li_trend["Clicks"] = pd.to_numeric(li_trend["Clicks (total)"], errors="coerce").fillna(0)
        li_trend["Impressions · 7-day avg"] = li_trend["Impressions"].rolling(7, min_periods=1).mean()
        li_fig = px.area(li_trend, x="Date", y="Impressions", template="plotly_white", color_discrete_sequence=["#bfdbfe"])
        li_fig.update_traces(name="Daily impressions", line=dict(color="#60a5fa", width=1.5), fillcolor="rgba(96,165,250,.22)")
        li_fig.add_scatter(x=li_trend["Date"], y=li_trend["Impressions · 7-day avg"], mode="lines", name="7-day average", line=dict(color="#0a66c2", width=3))
        li_fig.update_layout(title="LinkedIn impressions over time", height=400, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", yaxis_title="Impressions", legend_title_text="", hovermode="x unified", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
        show_chart(li_fig)

        follower_trend = li_followers.sort_values("Date").copy()
        follower_trend["Organic"] = pd.to_numeric(follower_trend.get("Organic followers"), errors="coerce").fillna(0)
        follower_trend["Sponsored"] = pd.to_numeric(follower_trend.get("Sponsored followers"), errors="coerce").fillna(0)
        follower_chart = follower_trend[["Date", "Organic", "Sponsored"]].melt("Date", var_name="Source", value_name="New followers")
        follower_fig = px.bar(follower_chart, x="Date", y="New followers", color="Source", barmode="stack", template="plotly_white", color_discrete_map={"Organic": "#0a66c2", "Sponsored": "#93c5fd"})
        follower_fig.update_layout(title="Daily follower growth", height=350, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", legend_title_text="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")

        visitor_trend = li_visitors.sort_values("Date").copy()
        visitor_trend["Page views"] = pd.to_numeric(visitor_trend.get("Total page views (total)"), errors="coerce").fillna(0)
        visitor_trend["Unique visitors"] = pd.to_numeric(visitor_trend.get("Total unique visitors (total)"), errors="coerce").fillna(0)
        visitor_chart = visitor_trend[["Date", "Page views", "Unique visitors"]].melt("Date", var_name="Metric", value_name="Count")
        visitor_fig = px.line(visitor_chart, x="Date", y="Count", color="Metric", template="plotly_white", color_discrete_sequence=["#7c3aed", "#10b981"])
        visitor_fig.update_layout(title="Page traffic", height=350, margin=dict(l=20, r=20, t=55, b=20), xaxis_title="", legend_title_text="", hovermode="x unified", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
        li_left, li_right = st.columns(2)
        with li_left: show_chart(follower_fig)
        with li_right: show_chart(visitor_fig)

        st.markdown("##### Follower audience breakdown")
        audience_files = {
            "Industries": "followers_industry",
            "Locations": "followers_location",
            "Job functions": "followers_job_function",
            "Seniority": "followers_seniority",
            "Company size": "followers_company_size",
        }
        audience_tabs = st.tabs(list(audience_files))
        for audience_tab, (label, file_name) in zip(audience_tabs, audience_files.items()):
            with audience_tab:
                breakdown = linkedin_csv(file_name)
                if not breakdown.empty:
                    value_column = "Total followers"
                    breakdown[value_column] = pd.to_numeric(breakdown[value_column], errors="coerce").fillna(0)
                    top = breakdown.nlargest(12, value_column).sort_values(value_column)
                    category_column = next(column for column in top.columns if column != value_column)
                    audience_fig = px.bar(top, x=value_column, y=category_column, orientation="h", template="plotly_white", color_discrete_sequence=["#0a66c2"])
                    audience_fig.update_layout(height=390, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="Followers", yaxis_title="", paper_bgcolor="white", plot_bgcolor="white", font_color="#334155")
                    show_chart(audience_fig)

        if not li_posts.empty:
            st.markdown("##### Recent LinkedIn posts in the export")
            li_posts["Created date"] = pd.to_datetime(li_posts["Created date"], errors="coerce")
            recent_li = li_posts.sort_values("Created date", ascending=False).head(30).copy()
            recent_li["Created date"] = recent_li["Created date"].dt.strftime("%Y-%m-%d")
            post_columns = ["Created date", "Post title", "Post type", "Impressions", "Clicks", "Likes", "Comments", "Reposts", "Post link"]
            st.dataframe(recent_li[[column for column in post_columns if column in recent_li]], width="stretch", hide_index=True, column_config={"Post link": st.column_config.LinkColumn("Open")})
    else:
        st.info("The static LinkedIn data files are unavailable in this deployment.")

with tab_posts:
    st.markdown("#### Recent channel content")
    st.caption("Posts and videos published during the selected reporting window.")
    content_facebook, content_instagram, content_youtube = st.tabs(["Facebook", "Instagram", "YouTube"])

    with content_facebook:
        posts = (meta_data or {}).get("posts", [])
        if posts:
            rows = []
            for post in posts:
                rows.append({
                    "Published": post.get("created_time", "")[:10],
                    "Type": facebook_post_type(post),
                    "Post": (post.get("message") or "(Media post)")[:160],
                    "Likes": post.get("likes", {}).get("summary", {}).get("total_count", 0),
                    "Comments": post.get("comments", {}).get("summary", {}).get("total_count", 0),
                    "Shares": post.get("shares", {}).get("count", 0),
                    "Link": post.get("permalink_url", ""),
                })
            facebook_frame = pd.DataFrame(rows)
            facebook_frame["Engagements"] = facebook_frame[["Likes", "Comments", "Shares"]].sum(axis=1)
            type_order = ["Live", "Photo", "Link", "Text", "Reel"]
            type_summary = (
                facebook_frame.groupby("Type", as_index=False)
                .agg(Posts=("Type", "size"), Engagements=("Engagements", "sum"))
            )
            type_summary["Type"] = pd.Categorical(type_summary["Type"], categories=type_order, ordered=True)
            type_summary = type_summary.sort_values("Type")

            volume_fig = px.bar(
                type_summary,
                x="Type",
                y="Posts",
                color="Type",
                text_auto=True,
                category_orders={"Type": type_order},
                color_discrete_map={"Live": "#ef4444", "Photo": "#7c3aed", "Link": "#2563eb", "Text": "#64748b", "Reel": "#ec4899"},
                template="plotly_white",
            )
            volume_fig.update_layout(
                title="Facebook post mix",
                height=330,
                margin=dict(l=20, r=20, t=55, b=20),
                xaxis_title="",
                yaxis_title="Posts",
                showlegend=False,
                paper_bgcolor="white",
                plot_bgcolor="white",
                font_color="#334155",
            )
            engagement_fig = px.bar(
                type_summary,
                x="Type",
                y="Engagements",
                color="Type",
                text_auto=True,
                category_orders={"Type": type_order},
                color_discrete_map={"Live": "#ef4444", "Photo": "#7c3aed", "Link": "#2563eb", "Text": "#64748b", "Reel": "#ec4899"},
                template="plotly_white",
            )
            engagement_fig.update_layout(
                title="Engagement by post type",
                height=330,
                margin=dict(l=20, r=20, t=55, b=20),
                xaxis_title="",
                yaxis_title="Likes + comments + shares",
                showlegend=False,
                paper_bgcolor="white",
                plot_bgcolor="white",
                font_color="#334155",
            )
            mix_left, mix_right = st.columns(2)
            with mix_left:
                show_chart(volume_fig)
            with mix_right:
                show_chart(engagement_fig)
            st.dataframe(
                facebook_frame.drop(columns=["Engagements"]),
                width="stretch",
                hide_index=True,
                column_config={"Link": st.column_config.LinkColumn("Open")},
            )
        else:
            st.info("No Facebook posts were returned for this reporting window.")
        if meta_data and meta_data.get("posts_error"):
            st.caption(f"Meta Posts API: {meta_data['posts_error']}")

    with content_instagram:
        instagram_media = (meta_data or {}).get("instagram_media", [])
        if instagram_media:
            rows = []
            for item in instagram_media:
                rows.append({
                    "Published": item.get("timestamp", "")[:10],
                    "Type": str(item.get("media_type", "")).replace("_", " ").title(),
                    "Caption": (item.get("caption") or "(No caption)")[:160],
                    "Likes": int_value(item.get("like_count")),
                    "Comments": int_value(item.get("comments_count")),
                    "Link": item.get("permalink", ""),
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={"Link": st.column_config.LinkColumn("Open")})
        else:
            st.info("No Instagram media was returned for this reporting window.")
        if meta_data and meta_data.get("instagram_media_error"):
            st.caption(f"Instagram Media API: {meta_data['instagram_media_error']}")

    with content_youtube:
        videos = (youtube_data or {}).get("videos", [])
        if videos:
            rows = []
            for video in videos:
                snippet = video.get("snippet", {})
                stats = video.get("statistics", {})
                video_id = video.get("id", "")
                rows.append({
                    "Published": snippet.get("publishedAt", "")[:10],
                    "Video": snippet.get("title", "(Untitled video)"),
                    "Views": int_value(stats.get("viewCount")),
                    "Likes": int_value(stats.get("likeCount")),
                    "Comments": int_value(stats.get("commentCount")),
                    "Link": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={"Link": st.column_config.LinkColumn("Open")})
        else:
            st.info("No YouTube videos were returned for this reporting window.")
        if youtube_data and youtube_data.get("videos_error"):
            st.caption(f"YouTube Data API: {youtube_data['videos_error']}")

st.caption(f"Reporting window: {start} through {end} · Data cached for 15 minutes · Last refreshed when this page loaded")
