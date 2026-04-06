"""
Streamlit Analyst Dashboard — Social Sentiment
────────────────────────────────────────────────
Exploratory UI for deep inspection. NOT the primary ops view (that's Grafana).
Port: 8501

Pages:
  1. Overview — hourly trend charts, current hour snapshot
  2. Post Explorer — filterable table of raw posts with sentiment
  3. Top Negatives — worst posts by neg score + derived labels
  4. Complaint Clusters — derived label breakdown
  5. Alert Log — recent alerts from alert_events

Run: streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import get_connection, fetch_hourly_aggregates
from config.settings import BRAND_QUERIES, DB_PATH

st.set_page_config(
    page_title="Yeet Brand Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar filters ──────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎰 Brand Intelligence")
    st.markdown("*Yeet Casino — Social Sentiment*")
    st.divider()

    selected_brand = st.selectbox("Brand / Query", BRAND_QUERIES)
    platform_opts  = ["ALL", "reddit", "twitter"]
    selected_plat  = st.selectbox("Platform", platform_opts)

    time_window = st.selectbox(
        "Time Window",
        ["Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days"],
        index=2,
    )
    WINDOW_H = {"Last 1 hour": 1, "Last 6 hours": 6, "Last 24 hours": 24, "Last 7 days": 168}
    hours = WINDOW_H[time_window]

    sentiment_filter = st.multiselect(
        "Sentiment Filter",
        ["positive", "neutral", "negative"],
        default=["positive", "neutral", "negative"],
    )
    label_opts = [
        "payment_issue", "login_issue", "scam_concern",
        "ux_praise", "support_complaint", "hype",
    ]
    label_filter = st.multiselect("Complaint / Label Filter", label_opts)

    st.divider()
    st.caption(f"DB: {DB_PATH}")
    if st.button("🔄 Refresh"):
        st.rerun()


# ── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def load_hourly(brand: str, platform: str, h: int) -> pd.DataFrame:
    rows = fetch_hourly_aggregates(brand, platform, hours=h)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["hour_bucket"] = pd.to_datetime(df["hour_bucket"])
    return df.sort_values("hour_bucket")


@st.cache_data(ttl=120)
def load_posts(brand: str, platform: str, h: int) -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    plat_clause = "" if platform == "ALL" else "AND sr.platform = :plat"
    df = pd.read_sql_query(
        f"""SELECT
              sr.sentiment_label, sr.sentiment_score,
              sr.relevance_score, sr.is_relevant,
              sr.derived_labels, sr.platform, sr.posted_at,
              np.clean_text,
              rp.author_handle, rp.likes, rp.upvotes, rp.post_url,
              run.query
            FROM sentiment_results sr
            JOIN normalized_posts np ON np.platform=sr.platform AND np.post_id=sr.post_id
            JOIN raw_posts rp ON rp.id = np.raw_post_id
            JOIN scrape_runs run ON run.run_id = rp.scrape_run_id
            WHERE run.query LIKE :brand
            AND sr.is_relevant = 1
            AND sr.posted_at >= datetime('now', :window)
            {plat_clause}
            ORDER BY sr.posted_at DESC
            LIMIT 2000""",
        conn,
        params={
            "brand": f"%{brand}%",
            "window": f"-{h} hours",
            "plat": platform,
        },
    )
    conn.close()
    if "derived_labels" in df.columns:
        df["derived_labels"] = df["derived_labels"].apply(
            lambda x: json.loads(x) if x else []
        )
    return df


@st.cache_data(ttl=300)
def load_alert_log() -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    df = pd.read_sql_query(
        """SELECT alert_name, severity, platform, brand_query,
                  trigger_value, threshold, message, fired_at, sent_ok
           FROM alert_events
           ORDER BY fired_at DESC LIMIT 100""",
        conn,
    )
    conn.close()
    return df


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Overview", "🔍 Post Explorer",
    "🔴 Top Negatives", "🏷 Complaint Clusters", "🚨 Alert Log",
])

# ─── Tab 1: Overview ─────────────────────────────────────────────────────────
with tab1:
    hourly_df = load_hourly(selected_brand, selected_plat, hours)

    if hourly_df.empty:
        st.warning("No hourly data for the selected filters.")
    else:
        # KPI row
        last = hourly_df.iloc[-1]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Relevant Mentions", int(last.get("relevant_posts", 0)))
        c2.metric("Positive %",
                  f"{(last.get('pos_ratio') or 0):.0%}",
                  delta=None)
        c3.metric("Negative %",
                  f"{(last.get('neg_ratio') or 0):.0%}",
                  delta=None)
        c4.metric("Weighted Sentiment",
                  f"{(last.get('weighted_sentiment') or 0):.3f}")
        c5.metric("Total Posts", int(last.get("total_posts", 0)))

        st.divider()

        # Mention volume chart
        st.subheader("Mention Volume")
        st.bar_chart(
            hourly_df.set_index("hour_bucket")[["relevant_posts", "total_posts"]]
        )

        # Sentiment ratio stacked area
        st.subheader("Sentiment Ratio Over Time")
        ratio_cols = ["pos_ratio", "neu_ratio", "neg_ratio"]
        available  = [c for c in ratio_cols if c in hourly_df.columns]
        if available:
            st.area_chart(hourly_df.set_index("hour_bucket")[available])

        # Weighted sentiment trend
        st.subheader("Weighted Sentiment Score (−1 = full negative, +1 = full positive)")
        if "weighted_sentiment" in hourly_df.columns:
            st.line_chart(hourly_df.set_index("hour_bucket")[["weighted_sentiment"]])


# ─── Tab 2: Post Explorer ─────────────────────────────────────────────────────
with tab2:
    post_df = load_posts(selected_brand, selected_plat, hours)

    if sentiment_filter:
        post_df = post_df[post_df["sentiment_label"].isin(sentiment_filter)]
    if label_filter:
        post_df = post_df[
            post_df["derived_labels"].apply(
                lambda labels: any(l in labels for l in label_filter)
            )
        ]

    st.markdown(f"**{len(post_df)} posts** matching filters")

    display_cols = [
        "posted_at", "platform", "sentiment_label", "sentiment_score",
        "relevance_score", "author_handle", "clean_text",
    ]
    show_cols = [c for c in display_cols if c in post_df.columns]
    st.dataframe(
        post_df[show_cols].head(500),
        use_container_width=True,
        column_config={
            "clean_text": st.column_config.TextColumn("Post Text", width="large"),
            "sentiment_score": st.column_config.NumberColumn("Confidence", format="%.3f"),
            "relevance_score": st.column_config.NumberColumn("Relevance", format="%.3f"),
        },
    )


# ─── Tab 3: Top Negatives ─────────────────────────────────────────────────────
with tab3:
    post_df_all = load_posts(selected_brand, selected_plat, hours)
    neg_df = post_df_all[post_df_all["sentiment_label"] == "negative"].copy()
    neg_df = neg_df.sort_values("sentiment_score", ascending=False).head(50)

    st.markdown(f"**{len(neg_df)} negative posts** in window")

    for _, row in neg_df.iterrows():
        with st.expander(
            f"[{row.get('platform','')}] {row.get('author_handle','anon')} — "
            f"score: {row.get('sentiment_score', 0):.3f} | "
            f"labels: {', '.join(row.get('derived_labels', []) or [])}"
        ):
            st.write(row.get("clean_text", ""))
            if row.get("post_url"):
                st.markdown(f"[View Original]({row['post_url']})")


# ─── Tab 4: Complaint Clusters ───────────────────────────────────────────────
with tab4:
    post_df_cl = load_posts(selected_brand, selected_plat, hours)
    from collections import Counter
    label_counts: Counter = Counter()
    for labels in post_df_cl["derived_labels"]:
        if labels:
            label_counts.update(labels)

    if label_counts:
        labels_df = pd.DataFrame(
            label_counts.most_common(), columns=["Label", "Count"]
        )
        st.bar_chart(labels_df.set_index("Label"))
        st.dataframe(labels_df, use_container_width=True)
    else:
        st.info("No derived labels in this window.")


# ─── Tab 5: Alert Log ────────────────────────────────────────────────────────
with tab5:
    alert_df = load_alert_log()
    if alert_df.empty:
        st.info("No alerts fired yet.")
    else:
        sev_color = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
        for _, row in alert_df.iterrows():
            ico = sev_color.get(row.get("severity", "info"), "⚪")
            with st.expander(
                f"{ico} {row['alert_name']} — {row.get('platform','')} — {row.get('fired_at','')}"
            ):
                st.write(row.get("message", ""))
                st.caption(
                    f"Trigger: {row.get('trigger_value', '')}  "
                    f"Threshold: {row.get('threshold', '')}  "
                    f"Sent: {'✓' if row.get('sent_ok') else '✗'}"
                )
