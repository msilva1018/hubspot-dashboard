"""
HubSpot KPI Dashboard — Streamlit app.

Run locally:
    streamlit run streamlit_app.py

Set your HubSpot private app token in .streamlit/secrets.toml as:
    hubspot_token = "pat-na1-xxxxxxxx..."
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from hubspot_client import (
    HubSpotError,
    get_email_statistics,
    get_email_statistics_intervals,
    get_recent_email_engagements,
    resolve_contact_names,
    resolve_file_names,
    summarize_engagements,
)

# ---------------------------------------------------------------------------
# Page config + auth
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="HubSpot KPI Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("📊 HubSpot KPI Dashboard")
st.caption("Email campaign performance and engagement, pulled live from the HubSpot API.")


def _get_token() -> str | None:
    """Read the HubSpot token from Streamlit secrets, or prompt for it."""
    token = st.secrets.get("hubspot_token") if hasattr(st, "secrets") else None
    if not token:
        token = st.sidebar.text_input(
            "HubSpot private app token",
            type="password",
            help="Paste your private app access token. Stored only for this session.",
        )
    return token or None


token = _get_token()
if not token:
    st.warning("Add `hubspot_token` to `.streamlit/secrets.toml` or paste it in the sidebar.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")
days_back = st.sidebar.slider("Look-back window (days)", 7, 180, 30)
interval = st.sidebar.selectbox(
    "Time-series interval",
    options=["DAY", "WEEK", "MONTH"],
    index=0,
)
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

end = datetime.now(timezone.utc)
start = end - timedelta(days=days_back)
st.sidebar.caption(f"Window: {start.date()} → {end.date()}")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_emails, tab_engagement, tab_docs = st.tabs(
    ["📧 Email Campaigns", "👥 Engagement", "📎 Documents"]
)

# ---- Email Campaigns -------------------------------------------------------
with tab_emails:
    try:
        stats = get_email_statistics(token, start, end)
    except HubSpotError as e:
        st.error(f"Could not load email statistics: {e}")
        st.stop()

    counters = stats.get("aggregate", {}).get("counters", {}) or {}
    ratios = stats.get("aggregate", {}).get("ratios", {}) or {}

    sent = counters.get("sent", 0)
    delivered = counters.get("delivered", 0)
    opens = counters.get("open", 0)
    clicks = counters.get("click", 0)
    bounces = counters.get("bounce", 0)
    unsubs = counters.get("unsubscribed", 0)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Sent", f"{sent:,}")
    c2.metric("Delivered", f"{delivered:,}")
    c3.metric("Opens", f"{opens:,}", f"{ratios.get('openratio', 0) * 100:.1f}%")
    c4.metric("Clicks", f"{clicks:,}", f"{ratios.get('clickratio', 0) * 100:.1f}%")
    c5.metric("Bounces", f"{bounces:,}")
    c6.metric("Unsubs", f"{unsubs:,}")

    st.subheader("Volume over time")
    try:
        series = get_email_statistics_intervals(token, start, end, interval=interval)
        intervals = series.get("results", []) or []
        rows = []
        for it in intervals:
            ts = it.get("interval", {}).get("start") or it.get("startTimestamp")
            counters_i = (it.get("aggregations", {}) or it.get("aggregate", {})).get(
                "counters", {}
            ) or {}
            rows.append(
                {
                    "timestamp": ts,
                    "sent": counters_i.get("sent", 0),
                    "open": counters_i.get("open", 0),
                    "click": counters_i.get("click", 0),
                }
            )
        if rows:
            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp")
            fig = px.line(
                df,
                x="timestamp",
                y=["sent", "open", "click"],
                markers=True,
                title=f"Email activity by {interval.lower()}",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No interval data returned for this window.")
    except HubSpotError as e:
        st.warning(f"Time-series unavailable: {e}")

# ---- Engagement ------------------------------------------------------------
with tab_engagement:
    st.subheader("Recent email engagements")
    st.caption(
        "Pulled from the engagements API. Useful for spotting which reps' emails "
        "are landing and which are not."
    )
    try:
        engagements = get_recent_email_engagements(token, since=start)
    except HubSpotError as e:
        st.error(f"Could not load engagements: {e}")
        engagements = []

    summary = summarize_engagements(engagements)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total emails", summary["total"])
    c2.metric("Opened", summary["opened"])
    c3.metric("Replied", summary["replied"])
    c4.metric("With attachment", summary["with_attachment"])

    if engagements:
        rows = []
        for item in engagements[:200]:
            eng = item.get("engagement", {})
            meta = item.get("metadata", {})
            rows.append(
                {
                    "id": eng.get("id"),
                    "createdAt": pd.to_datetime(eng.get("createdAt"), unit="ms"),
                    "from": (meta.get("from") or {}).get("email"),
                    "subject": meta.get("subject"),
                    "status": meta.get("emailStatus"),
                    "openCount": meta.get("openCount", 0),
                    "replyCount": meta.get("replyCount", 0),
                    "hasAttachment": bool(item.get("attachments")),
                }
            )
        df_eng = pd.DataFrame(rows).sort_values("createdAt", ascending=False)
        st.dataframe(df_eng, use_container_width=True, hide_index=True)
    else:
        st.info("No email engagements found in this window.")

# ---- Documents -------------------------------------------------------------
with tab_docs:
    st.subheader("Document viewers")
    st.caption(
        "Pick a document below to see who opened the email it was attached to."
    )

    if not engagements:
        st.write("No engagements loaded — check the Engagement tab.")
    else:
        # Build a flat list of (engagement, attachment) rows
        doc_rows = []
        for item in engagements:
            attachments = item.get("attachments") or []
            if not attachments:
                continue
            eng = item.get("engagement", {})
            meta = item.get("metadata", {})
            assoc = item.get("associations", {}) or {}
            contact_ids = assoc.get("contactIds", []) or []
            for att in attachments:
                doc_rows.append(
                    {
                        "engagementId": eng.get("id"),
                        "createdAt": pd.to_datetime(eng.get("createdAt"), unit="ms"),
                        "subject": meta.get("subject"),
                        "attachmentId": str(att.get("id")),
                        "openCount": meta.get("openCount", 0),
                        "contactIds": contact_ids,
                    }
                )

        if not doc_rows:
            st.write("No email engagements with attachments in this window.")
        else:
            df_docs = pd.DataFrame(doc_rows)

            # Resolve attachment IDs → friendly names (requires `files` scope)
            with st.spinner("Loading document names..."):
                name_map = resolve_file_names(
                    token, df_docs["attachmentId"].unique().tolist()
                )

            # Only keep rows where we successfully resolved a real name.
            # If name_map returned the "Document {id}" fallback, the `files`
            # scope is probably missing — warn the user explicitly.
            df_docs["document"] = df_docs["attachmentId"].map(name_map)
            unresolved = df_docs["document"].str.startswith("Document ", na=False)
            if unresolved.all():
                st.error(
                    "Couldn't resolve any document names. This usually means the "
                    "`files` scope is missing from your private app. Add it under "
                    "Settings → Integrations → Private Apps → your app → Scopes.",
                    icon="⚠️",
                )
                st.stop()
            elif unresolved.any():
                st.warning(
                    f"{unresolved.sum()} attachment(s) couldn't be resolved to "
                    "names (possibly deleted from the file manager). They're "
                    "hidden from the dropdown.",
                    icon="ℹ️",
                )
                df_docs = df_docs[~unresolved]

            # Dropdown: single document, names only
            doc_names = sorted(df_docs["document"].unique().tolist())
            selected_doc = st.selectbox(
                "Document",
                options=doc_names,
                index=0 if doc_names else None,
                placeholder="Choose a document…",
            )

            df_filtered = df_docs[df_docs["document"] == selected_doc]

            # Headline metrics for this doc
            total_sends = len(df_filtered)
            df_viewed = df_filtered[df_filtered["openCount"] > 0]
            unique_viewers = len(
                {cid for cids in df_viewed["contactIds"] for cid in cids}
            )

            c1, c2, c3 = st.columns(3)
            c1.metric("Times sent", total_sends)
            c2.metric("Times opened", int(df_filtered["openCount"].sum()))
            c3.metric("Unique viewers", unique_viewers)

            # Viewer list — only contacts whose email was actually opened
            st.markdown(f"**People who opened an email containing _{selected_doc}_**")

            viewer_rows = []
            for _, row in df_viewed.iterrows():
                for cid in row["contactIds"]:
                    viewer_rows.append(
                        {
                            "contactId": str(cid),
                            "sentAt": row["createdAt"],
                            "subject": row["subject"],
                        }
                    )

            if not viewer_rows:
                st.info(
                    "No opens recorded for this document yet.",
                    icon="📭",
                )
            else:
                df_viewers = pd.DataFrame(viewer_rows)
                with st.spinner("Loading viewer names…"):
                    contact_map = resolve_contact_names(
                        token, df_viewers["contactId"].unique().tolist()
                    )
                df_viewers["name"] = df_viewers["contactId"].map(
                    lambda c: contact_map.get(c, {}).get("name", "")
                )
                df_viewers["email"] = df_viewers["contactId"].map(
                    lambda c: contact_map.get(c, {}).get("email", "")
                )

                # One row per viewer, with their most recent open
                df_unique = (
                    df_viewers.sort_values("sentAt", ascending=False)
                    .drop_duplicates(subset=["contactId"])
                    .loc[:, ["name", "email", "sentAt", "subject"]]
                    .rename(
                        columns={
                            "sentAt": "Last opened",
                            "subject": "Email subject",
                        }
                    )
                )
                st.dataframe(df_unique, use_container_width=True, hide_index=True)

                st.caption(
                    "Note: 'opened' reflects an email open, not strictly a "
                    "document view. For true document-view + time-spent data, "
                    "the HubSpot UI's Sales Content Analytics or a tool like "
                    "CloudFiles is needed."
                )

st.divider()
st.caption(
    "Data cached for 10 minutes. Use the Refresh button in the sidebar to force a reload."
)
