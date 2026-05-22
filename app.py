import json
from pathlib import Path

import geopandas as gpd
import folium
import joblib
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

PROJECT_ROOT = Path(__file__).resolve().parent
GEOJSON_PATH = PROJECT_ROOT / "output" / "master.geojson"
MODEL_PATH = PROJECT_ROOT / "output" / "demographic_model.joblib"
MODEL_METADATA_PATH = PROJECT_ROOT / "output" / "demographic_model.json"

OVERLAY_OPTIONS = {
    "Risk Score": {"col": "risk_score", "fmt": "{:.1f}", "legend": "Underservice Risk Score (0–100)"},
    "Unexplained Neglect (Residual)": {
        "col": "risk_residual", "fmt": "{:+.1f}",
        "legend": "Risk Score − RF Prediction (red = more neglect than demographics predict)",
    },
    "Predicted Risk (from demographics)": {
        "col": "predicted_risk", "fmt": "{:.1f}",
        "legend": "Random Forest Prediction (0–100)",
    },
    "Median Income": {"col": "median_income", "fmt": "${:,.0f}", "legend": "Median Household Income ($)"},
    "Poverty Rate": {"col": "poverty_rate", "fmt": "{:.1%}", "legend": "Poverty Rate"},
    "% Black": {"col": "pct_black", "fmt": "{:.1%}", "legend": "% Black / African American"},
    "% Hispanic": {"col": "pct_hispanic", "fmt": "{:.1%}", "legend": "% Hispanic or Latino"},
    "% Foreign-Born": {"col": "pct_foreign_born", "fmt": "{:.1%}", "legend": "% Foreign-Born"},
    "Rent Burden": {"col": "rent_burden", "fmt": "{:.1%}", "legend": "% Renters Paying ≥50% Income on Rent"},
    "Unemployment": {"col": "unemployment_rate", "fmt": "{:.1%}", "legend": "Unemployment Rate"},
    "% Bachelor's+": {"col": "pct_bachelors", "fmt": "{:.1%}", "legend": "% with Bachelor's Degree or Higher"},
}

st.set_page_config(page_title="Underservice Risk Index", layout="wide")

st.markdown(
    """
    <style>
    .metric-box { background: #1e1e2e; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; }
    .metric-label { font-size: 0.75rem; color: #aaa; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-value { font-size: 1.4rem; font-weight: 700; color: #fff; }
    .metric-compare { font-size: 0.8rem; color: #f4a261; }
    .risk-score { font-size: 3rem; font-weight: 900; }
    .neighborhood-name { font-size: 1.4rem; font-weight: 700; color: #fff; line-height: 1.1; }
    .borough-tag { font-size: 0.85rem; color: #f4a261; text-transform: uppercase; letter-spacing: 0.08em; }
    .tract-id { font-size: 0.75rem; color: #888; font-family: monospace; }

    /* Hide the now-unused Streamlit sidebar and its toggle button */
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] { display: none !important; }

    /* ── Floating tab bar ── */
    /* Pin the tab list to the top of the viewport, below the Streamlit
       header. The tab panels scroll normally underneath it. */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        position: fixed;
        top: 40px;
        left: 0;
        right: 0;
        z-index: 1100;
        background: rgba(12, 12, 20, 0.96);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-bottom: 1px solid rgba(255, 255, 255, 0.09);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
        padding: 0px 28px 0;
        gap: 4px;
        align-items: flex-end;
        min-height: 52px;
        overflow: visible;
    }
    /* Individual tab buttons */
    [data-testid="stTabs"] [data-baseweb="tab"] {
        color: #888;
        font-size: 0.82rem;
        font-weight: 500;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        line-height: 1.5;
        padding: 8px 16px 10px;
        height: auto !important;
        min-height: 0 !important;
        border-radius: 0;
        background: transparent !important;
        border-bottom: 2px solid transparent;
        transition: color 0.15s, border-color 0.15s;
    }
    [data-testid="stTabs"] [data-baseweb="tab"]:hover {
        color: #ddd;
        border-bottom-color: rgba(244, 162, 97, 0.4);
    }
    [data-testid="stTabs"] [aria-selected="true"][data-baseweb="tab"] {
        color: #f4a261 !important;
        border-bottom-color: #f4a261 !important;
        background: transparent !important;
    }
    /* Hide the default animated underline — we draw our own via border-bottom */
    [data-testid="stTabs"] [data-baseweb="tab-highlight"] { display: none !important; }
    [data-testid="stTabs"] [data-baseweb="tab-border"]    { display: none !important; }

    /* Push tab-panel content below the fixed bar so nothing is hidden.
       Tab list now sits at top:56 + ~52px height = 108px from viewport top. */
    [data-testid="stTabs"] [data-baseweb="tab-panel"] {
        padding-top: 10px !important;
    }

    /* Shared floating-card style */
    .st-key-floating-filters, .st-key-floating-detail {
        position: fixed;
        z-index: 1000;
        max-height: 72vh;
        overflow-y: auto;
        background: rgba(20, 20, 32, 0.92);
        border-radius: 12px;
        padding: 14px 18px 16px;
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.55);
        backdrop-filter: blur(14px);
        -webkit-backdrop-filter: blur(14px);
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    /* Bump cards down to clear the floating tab bar */
    .st-key-floating-filters { top: 110px; left: 28px; width: 290px; }
    .st-key-floating-detail  { top: 110px; right: 28px; width: 370px; }

    /* Drag handle injected at the top of each floating card */
    .drag-handle {
        height: 18px;
        margin: -14px -18px 10px;
        padding: 5px 0;
        cursor: grab;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px 12px 0 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .drag-handle:active { cursor: grabbing; }
    .drag-handle::after {
        content: "";
        display: block;
        width: 40px;
        height: 3px;
        background: #666;
        border-radius: 2px;
    }

    /* Tighter widget spacing inside floating cards */
    .st-key-floating-filters [data-testid="stRadio"] label p,
    .st-key-floating-detail  [data-testid="stRadio"] label p { font-size: 0.9rem; }
    .st-key-floating-filters .stCaption, .st-key-floating-detail .stCaption {
        font-size: 0.72rem; line-height: 1.35;
    }

    /* Chatbot placeholder (watchlist tab, right half) */
    .chatbot-wrap {
        display: flex; flex-direction: column;
        height: 640px;
        background: #15151f;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        overflow: hidden;
    }
    .chatbot-header {
        padding: 12px 16px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        display: flex; align-items: center; gap: 10px;
        background: rgba(244, 162, 97, 0.08);
    }
    .chatbot-header .dot {
        width: 8px; height: 8px; border-radius: 50%;
        background: #f4a261; box-shadow: 0 0 8px rgba(244, 162, 97, 0.7);
    }
    .chatbot-header .title { font-weight: 600; color: #fff; }
    .chatbot-header .tag {
        margin-left: auto; font-size: 0.65rem;
        padding: 3px 7px; border-radius: 4px;
        background: rgba(255,255,255,0.08); color: #aaa;
        text-transform: uppercase; letter-spacing: 0.08em;
    }
    .chatbot-messages {
        flex: 1; padding: 16px; overflow-y: auto;
        display: flex; flex-direction: column; gap: 12px;
    }
    .chat-msg { max-width: 88%; padding: 10px 14px; border-radius: 10px; line-height: 1.4; font-size: 0.88rem; }
    .chat-msg.bot { align-self: flex-start; background: #22222f; color: #ddd; }
    .chat-msg.user { align-self: flex-end; background: #2a3b4f; color: #fff; }
    .chat-msg .meta { font-size: 0.65rem; color: #888; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
    .chatbot-input {
        display: flex; gap: 8px;
        padding: 12px; border-top: 1px solid rgba(255,255,255,0.08);
        background: #1a1a25;
    }
    .chatbot-input input {
        flex: 1; padding: 9px 12px;
        background: #22222f; color: #666;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 7px; font-size: 0.88rem;
    }
    .chatbot-input button {
        padding: 8px 16px; background: #333; color: #777;
        border: none; border-radius: 7px;
        font-size: 0.85rem; cursor: not-allowed;
    }

    /* Watchlist HTML table (right-clickable rows) */
    .watchlist-wrap {
        max-height: 640px; overflow: auto; border-radius: 8px;
        border: 1px solid rgba(255, 255, 255, 0.06);
    }
    .watchlist-table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
    .watchlist-table th {
        position: sticky; top: 0; background: #1e1e2e;
        text-align: left; padding: 10px 14px;
        color: #888; font-weight: 600; font-size: 0.68rem;
        text-transform: uppercase; letter-spacing: 0.06em;
        border-bottom: 1px solid rgba(255, 255, 255, 0.12);
    }
    .watchlist-table td {
        padding: 10px 14px; color: #ddd;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    .watchlist-table td.num { font-variant-numeric: tabular-nums; text-align: right; }
    .watchlist-table tbody tr { cursor: context-menu; }
    .watchlist-table tbody tr:hover { background: rgba(255, 255, 255, 0.04); }
    .watchlist-table td.name { color: #fff; font-weight: 500; }
    .watchlist-table td.pos { color: #e63946; }
    .watchlist-table td.neg { color: #2ec4b6; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_data():
    gdf = gpd.read_file(GEOJSON_PATH)
    return gdf


@st.cache_data
def geojson_dict(_gdf: gpd.GeoDataFrame, n_rows: int) -> dict:
    """Serializing the full GeoDataFrame to a GeoJSON dict is the dominant
    cost on every Folium re-render. Cache it keyed on row count so a
    pipeline rerun (which changes len) busts the cache."""
    return json.loads(_gdf.to_json())


@st.cache_resource
def load_model():
    if not MODEL_PATH.exists() or not MODEL_METADATA_PATH.exists():
        return None, None
    model = joblib.load(MODEL_PATH)
    with open(MODEL_METADATA_PATH) as f:
        metadata = json.load(f)
    return model, metadata


def render_chatbot_placeholder():
    """Static placeholder for a future RAG LLM chatbot. No backend wired up."""
    html = """
    <div class="chatbot-wrap">
      <div class="chatbot-header">
        <div class="dot"></div>
        <div class="title">Ask the Index</div>
        <div class="tag">Coming Soon</div>
      </div>
      <div class="chatbot-messages">
        <div class="chat-msg bot">
          <div class="meta">Assistant</div>
          Hi — I&rsquo;ll eventually answer questions about any NYC tract using the
          underlying 311, HPD, ACS, and vacate-order data. Example prompts:
        </div>
        <div class="chat-msg bot">
          <div class="meta">Example</div>
          &ldquo;Why does East Tremont have a +22 residual?&rdquo;
        </div>
        <div class="chat-msg bot">
          <div class="meta">Example</div>
          &ldquo;Which Brooklyn tracts are most underserved relative to their income level?&rdquo;
        </div>
        <div class="chat-msg bot">
          <div class="meta">Example</div>
          &ldquo;Summarize the housing complaint profile for tract 36061020900.&rdquo;
        </div>
      </div>
      <div class="chatbot-input">
        <input type="text" placeholder="Chat disabled — RAG backend not yet connected" disabled />
        <button disabled>Send</button>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def correlation_with_risk(gdf: gpd.GeoDataFrame) -> pd.Series:
    cols = [v["col"] for k, v in OVERLAY_OPTIONS.items() if k != "Risk Score"]
    cols = [c for c in cols if c in gdf.columns]
    df = pd.DataFrame(gdf[cols + ["risk_score"]]).dropna()
    return df.corr(numeric_only=True)["risk_score"].drop("risk_score").sort_values(
        key=lambda s: s.abs(), ascending=False
    )


def make_map(
    gdf: gpd.GeoDataFrame,
    overlay_label: str,
    center: list | None = None,
    zoom: int = 11,
    highlight_geoid: str | None = None,
) -> folium.Map:
    if center is None:
        center = [40.7128, -74.0060]
    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB positron")

    overlay = OVERLAY_OPTIONS[overlay_label]
    value_col = overlay["col"]
    # Invert color scale for "protective" demographics where higher = less underserved
    reverse_scale = overlay_label in {"Median Income", "% Bachelor's+"}
    color_scheme = "RdYlGn" if reverse_scale else "RdYlGn_r"

    # Drop nulls for the active column so Folium assigns colors correctly
    chloro_df = gdf[["GEOID", value_col]].dropna()

    geojson_data = geojson_dict(gdf, len(gdf))

    choropleth_kwargs = dict(
        geo_data=geojson_data,
        name=overlay_label,
        data=chloro_df,
        columns=["GEOID", value_col],
        key_on="feature.properties.GEOID",
        fill_color=color_scheme,
        fill_opacity=0.75,
        line_opacity=0.2,
        legend_name=overlay["legend"],
        nan_fill_color="lightgray",
    )

    # For the residual layer, force symmetric bins centered on 0 so the color
    # tracks magnitude (not rank). Tracts inside ±5 sit inside the RMSE noise
    # floor and stay muted; |residual| > 20 pops as a genuine outlier.
    if value_col == "risk_residual" and len(chloro_df) > 0:
        abs_max = float(np.nanmax(np.abs(chloro_df[value_col].values)))
        edge = max(25.0, np.ceil(abs_max / 5.0) * 5.0)
        choropleth_kwargs["bins"] = [-edge, -20, -10, 0, 10, 20, edge]

    folium.Choropleth(**choropleth_kwargs).add_to(m)

    tooltip_fields = ["neighborhood", "borough", "GEOID", "risk_score",
                      "avg_closure_time", "accountability_gap"]
    tooltip_aliases = ["Neighborhood", "Borough", "Tract", "Risk Score",
                       "Avg Closure (days)", "Accountability Gap"]
    if value_col not in tooltip_fields and value_col in gdf.columns:
        tooltip_fields.append(value_col)
        tooltip_aliases.append(overlay_label)
    available = [(f, a) for f, a in zip(tooltip_fields, tooltip_aliases) if f in gdf.columns]
    fields = [f for f, _ in available]
    aliases = [a for _, a in available]

    folium.GeoJson(
        geojson_data,
        style_function=lambda _f: {
            "fillOpacity": 0,
            "weight": 0,
        },
        highlight_function=lambda _f: {
            "weight": 2,
            "color": "#ffffff",
            "fillOpacity": 0.1,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=fields,
            aliases=aliases,
            localize=True,
        ),
    ).add_to(m)

    # Outline the selected tract so it's obvious what the detail panel refers to
    if highlight_geoid:
        sel = gdf[gdf["GEOID"] == highlight_geoid]
        if len(sel) > 0:
            folium.GeoJson(
                json.loads(sel.to_json()),
                style_function=lambda _f: {
                    "fillOpacity": 0,
                    "color": "#ffffff",
                    "weight": 4,
                    "opacity": 0.95,
                    "dashArray": "6, 4",
                },
                interactive=False,
            ).add_to(m)

    return m


def sidebar_panel(tract_props: dict, citywide: dict):
    score = tract_props.get("risk_score", None)
    neighborhood = tract_props.get("neighborhood") or "Unknown Neighborhood"
    borough = tract_props.get("borough") or ""
    geoid = tract_props.get("GEOID", "—")

    score_color = "#e63946" if score and score >= 75 else "#f4a261" if score and score >= 50 else "#2ec4b6"

    # Header: neighborhood + borough + tract
    st.markdown(
        f'<div class="neighborhood-name">{neighborhood}</div>'
        f'<div class="borough-tag">{borough}</div>'
        f'<div class="tract-id">Tract {geoid}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("")

    st.markdown(
        f'<div style="text-align:center"><span class="risk-score" style="color:{score_color}">'
        f'{score:.1f}</span><br><span style="color:#aaa">Underservice Risk Score</span></div>',
        unsafe_allow_html=True,
    )
    st.divider()

    def metric_row(label, value, citywide_val, fmt="{:.2f}", unit=""):
        if value is None or citywide_val is None or citywide_val == 0:
            st.markdown(
                f'<div class="metric-box"><div class="metric-label">{label}</div>'
                f'<div class="metric-value">{fmt.format(value) + unit if value is not None else "N/A"}</div></div>',
                unsafe_allow_html=True,
            )
        else:
            ratio = value / citywide_val
            direction = "higher" if ratio > 1 else "lower"
            compare = f"{ratio:.1f}× {direction} than city avg"
            st.markdown(
                f'<div class="metric-box"><div class="metric-label">{label}</div>'
                f'<div class="metric-value">{fmt.format(value) + unit}</div>'
                f'<div class="metric-compare">{compare}</div></div>',
                unsafe_allow_html=True,
            )

    metric_row(
        "Avg 311 Closure Time",
        tract_props.get("avg_closure_time"),
        citywide.get("avg_closure_time"),
        fmt="{:.1f}", unit=" days",
    )
    metric_row(
        "Accountability Gap",
        tract_props.get("accountability_gap"),
        citywide.get("accountability_gap"),
        fmt="{:.2f}", unit="",
    )
    metric_row(
        "Severity-Weighted Violation Rate",
        tract_props.get("weighted_violation_rate"),
        citywide.get("weighted_violation_rate"),
        fmt="{:.3f}", unit="",
    )
    metric_row(
        "Vacate Order Rate",
        tract_props.get("vacate_rate"),
        citywide.get("vacate_rate"),
        fmt="{:.4f}", unit="",
    )
    metric_row(
        "Median Household Income",
        tract_props.get("median_income"),
        citywide.get("median_income"),
        fmt="${:,.0f}", unit="",
    )


def main():
    try:
        gdf = load_data()
    except Exception as e:
        st.error(f"Could not load master.geojson: {e}\nRun the pipeline first: `python -m pipeline.score`")
        return

    citywide = {
        col: gdf[col].mean() if col in gdf.columns else None
        for col in [
            "avg_closure_time", "median_income", "accountability_gap",
            "weighted_violation_rate", "vacate_rate", "mean_commute_time",
        ]
    }

    if "active_geoid" not in st.session_state:
        st.session_state.active_geoid = None
    if "last_click_key" not in st.session_state:
        st.session_state.last_click_key = None
    if "jump_to_map" not in st.session_state:
        st.session_state.jump_to_map = False

    # A right-click → "Show on map" in the Watchlist tab sets ?jump=<GEOID> and
    # reloads the page. Session state survives the reload; tabs reset to Map
    # (the first tab), so we naturally land there with the tract highlighted.
    if "jump" in st.query_params:
        jump_geoid = str(st.query_params["jump"])
        if jump_geoid:
            st.session_state.active_geoid = jump_geoid
            st.session_state.last_click_key = None
            st.session_state.jump_to_map = True
        del st.query_params["jump"]

    tab_map, tab_watch, tab_demo, tab_pred, tab_method = st.tabs(
        ["Map", "Watchlist", "Demographics", "Predictor", "Methodology"]
    )

    # --- Map tab ---------------------------------------------------------
    with tab_map:
        # Floating filter card (top-left, overlays the map)
        with st.container(key="floating-filters"):
            st.markdown("**Map Overlay**")
            st.radio(
                "Layer",
                list(OVERLAY_OPTIONS.keys()),
                index=0,
                label_visibility="collapsed",
                key="overlay_label",
            )
            st.caption(
                "Green → low, Red → high. Income / education invert (higher = better). "
                "**Unexplained Neglect** = red means neglect exceeding what demographics "
                "predict. Fixed bins ±10 / ±20; inside ±10 is RMSE noise floor."
            )
        overlay_label = st.session_state.overlay_label

        # Auto-pan: center map on the selected tract's centroid, shift ~1km west
        # so the right-side detail card doesn't cover it.
        map_center = [40.7128, -74.0060]
        map_zoom = 11
        if st.session_state.active_geoid:
            sel = gdf[gdf["GEOID"] == st.session_state.active_geoid]
            if len(sel) > 0:
                centroid = sel.iloc[0].geometry.centroid
                map_center = [centroid.y, centroid.x - 0.010]
                map_zoom = 14

        m = make_map(
            gdf, overlay_label,
            center=map_center, zoom=map_zoom,
            highlight_geoid=st.session_state.active_geoid,
        )
        map_key = f"map_{overlay_label}_{st.session_state.active_geoid or 'none'}"
        map_result = st_folium(
            m, width="100%", height=780,
            returned_objects=["last_clicked"],
            key=map_key,
        )

        # Click dedup — st_folium's last_clicked persists across reruns
        clicked = map_result.get("last_clicked") if map_result else None
        if clicked:
            click_key = (round(clicked["lat"], 6), round(clicked["lng"], 6))
            if click_key != st.session_state.last_click_key:
                st.session_state.last_click_key = click_key
                from shapely.geometry import Point
                pt = Point(clicked["lng"], clicked["lat"])
                candidate_idx = list(gdf.sindex.query(pt, predicate="contains"))
                match = gdf.iloc[candidate_idx]
                if len(match) == 0:
                    match = gdf.iloc[[gdf.geometry.distance(pt).argmin()]]
                if len(match) > 0:
                    new_geoid = match.iloc[0]["GEOID"]
                    if new_geoid != st.session_state.active_geoid:
                        st.session_state.active_geoid = new_geoid
                        st.rerun()

        # Floating detail card (top-right, only when a tract is active)
        if st.session_state.active_geoid:
            row = gdf[gdf["GEOID"] == st.session_state.active_geoid]
            if len(row) > 0:
                with st.container(key="floating-detail"):
                    header_col, close_col = st.columns([10, 1])
                    with header_col:
                        st.markdown("**Neighborhood Detail**")
                    with close_col:
                        if st.button("✕", key="close_detail", help="Close panel"):
                            st.session_state.active_geoid = None
                            st.session_state.last_click_key = None
                            st.rerun()
                    props = row.iloc[0].to_dict()
                    props.pop("geometry", None)
                    sidebar_panel(props, citywide)

    # --- Watchlist tab ---------------------------------------------------
    with tab_watch:
        st.subheader("Top Residual Outliers — Where Neglect Diverges From Demographics")
        st.caption(
            "Each row is a tract whose risk score is notably **higher** or **lower** "
            "than its demographics predict. Positive residual = more underserved "
            "than poverty/race/education alone would suggest. |residual| < 10 is "
            "within the model's noise floor — focus on the tail."
        )

        if "risk_residual" not in gdf.columns or not gdf["risk_residual"].notna().any():
            st.info(
                "Residuals not available. Run `python -m pipeline.demographic_analysis` "
                "to populate `predicted_risk` and `risk_residual` on the GeoJSON."
            )
        else:
            ctrl_dir, ctrl_n, ctrl_boro = st.columns([2, 1, 1])
            with ctrl_dir:
                st.radio(
                    "Ranking",
                    [
                        "Most unexplained neglect (+)",
                        "Unexpected success (−)",
                        "Biggest surprises (|residual|)",
                    ],
                    horizontal=True,
                    label_visibility="collapsed",
                    key="watchlist_direction",
                )
            with ctrl_n:
                st.slider(
                    "Show top",
                    min_value=10, max_value=50, value=20, step=5,
                    key="watchlist_top_n",
                )
            with ctrl_boro:
                boroughs = sorted(b for b in gdf["borough"].dropna().unique() if b)
                st.multiselect(
                    "Borough", boroughs, default=boroughs,
                    label_visibility="collapsed",
                    placeholder="Filter by borough",
                    key="watchlist_boroughs",
                )

            direction = st.session_state.watchlist_direction
            top_n = st.session_state.watchlist_top_n
            borough_filter = st.session_state.watchlist_boroughs

            subset = gdf[gdf["risk_residual"].notna()].copy()
            if borough_filter:
                subset = subset[subset["borough"].isin(borough_filter)]

            if direction.startswith("Most"):
                subset = subset.sort_values("risk_residual", ascending=False)
            elif direction.startswith("Unexpected"):
                subset = subset.sort_values("risk_residual", ascending=True)
            else:
                subset = subset.reindex(
                    subset["risk_residual"].abs().sort_values(ascending=False).index
                )

            # Row-level GEOID is retained on the <tr> for the right-click jump,
            # but kept out of display_cols to free horizontal space.
            table = subset.head(top_n)[[
                "neighborhood", "borough", "GEOID", "risk_score", "risk_residual",
            ]].copy()
            pretty_cols = {
                "neighborhood": "Neighborhood",
                "borough": "Borough",
                "risk_score": "Risk",
                "risk_residual": "Residual",
            }
            table = table.rename(columns=pretty_cols).round(2)

            st.caption("**Right-click a row** to jump to that tract on the map.")

            left_col, right_col = st.columns([1, 1], gap="large")

            with left_col:
                def fmt_val(col: str, val) -> str:
                    if pd.isna(val):
                        return ""
                    if col == "Residual":
                        return f"{val:+.1f}"
                    if col == "Risk":
                        return f"{val:.1f}"
                    if isinstance(val, float):
                        return f"{val:.2f}"
                    return str(val)

                numeric_cols = {"Risk", "Residual"}
                name_col = "Neighborhood"
                display_cols = ["Neighborhood", "Borough", "Risk", "Residual"]

                header_html = "".join(f"<th>{c}</th>" for c in display_cols)
                body_rows = []
                for _, r in table.iterrows():
                    geoid_attr = str(r.get("GEOID", "")).replace('"', "&quot;")
                    name_attr = str(r.get(name_col, "")).replace('"', "&quot;")
                    cells = []
                    for c in display_cols:
                        v = r[c]
                        txt = fmt_val(c, v)
                        classes = []
                        if c in numeric_cols:
                            classes.append("num")
                        if c == name_col:
                            classes.append("name")
                        if c == "Residual" and pd.notna(v):
                            classes.append("pos" if v > 0 else "neg" if v < 0 else "")
                        cls = f' class="{" ".join(c2 for c2 in classes if c2)}"' if classes else ""
                        cells.append(f"<td{cls}>{txt}</td>")
                    body_rows.append(
                        f'<tr data-geoid="{geoid_attr}" data-name="{name_attr}">'
                        f'{"".join(cells)}</tr>'
                    )
                table_html = (
                    '<div class="watchlist-wrap"><table class="watchlist-table">'
                    f'<thead><tr>{header_html}</tr></thead>'
                    f'<tbody>{"".join(body_rows)}</tbody>'
                    '</table></div>'
                )
                st.markdown(table_html, unsafe_allow_html=True)

            with right_col:
                render_chatbot_placeholder()

            # Context menu: right-click a row → "Show on map".
            # We inject a <script> into the PARENT document (not the component
            # iframe) so the closures that own the click handler aren't destroyed
            # on every Streamlit rerun — otherwise the "Show on map" click fires
            # into a dead scope and nothing happens.
            components.html(
                """
                <script>
                (function() {
                    const parentDoc = window.parent.document;
                    if (parentDoc.getElementById('__watchlist_ctx_script__')) return;
                    const s = parentDoc.createElement('script');
                    s.id = '__watchlist_ctx_script__';
                    s.textContent = `
                        (function() {
                            const menu = document.createElement('div');
                            menu.id = 'watchlist-context-menu';
                            menu.style.cssText =
                                'position:fixed;z-index:10000;background:#1e1e2e;' +
                                'border:1px solid rgba(255,255,255,0.12);border-radius:8px;' +
                                'padding:6px 0;box-shadow:0 8px 24px rgba(0,0,0,0.6);' +
                                'display:none;min-width:190px;color:#fff;font-size:0.88rem;' +
                                'font-family:-apple-system,BlinkMacSystemFont,sans-serif;';
                            document.body.appendChild(menu);

                            let curGeoid = null;
                            function hideMenu() { menu.style.display = 'none'; }

                            function showMenu(x, y, geoid, name) {
                                curGeoid = geoid;
                                menu.innerHTML =
                                    '<div style="padding:7px 14px;color:#888;' +
                                    'font-size:0.72rem;border-bottom:1px solid ' +
                                    'rgba(255,255,255,0.08);white-space:nowrap;' +
                                    'overflow:hidden;text-overflow:ellipsis;' +
                                    'max-width:260px;">' + (name || geoid) + '</div>' +
                                    '<div class="wl-item" style="padding:10px 14px;' +
                                    'cursor:pointer;">Show on map</div>';
                                const item = menu.querySelector('.wl-item');
                                item.addEventListener('mouseenter', function() {
                                    item.style.background = 'rgba(244,162,97,0.16)';
                                });
                                item.addEventListener('mouseleave', function() {
                                    item.style.background = '';
                                });
                                item.addEventListener('click', function() {
                                    const g = curGeoid;
                                    hideMenu();
                                    if (!g) return;
                                    const url = new URL(window.location.href);
                                    url.searchParams.set('jump', g);
                                    window.location.href = url.toString();
                                });
                                const mw = 220, mh = 90;
                                menu.style.left =
                                    Math.min(x, window.innerWidth - mw - 10) + 'px';
                                menu.style.top =
                                    Math.min(y, window.innerHeight - mh - 10) + 'px';
                                menu.style.display = 'block';
                            }

                            document.addEventListener('contextmenu', function(e) {
                                const row = e.target.closest(
                                    '.watchlist-table tr[data-geoid]'
                                );
                                if (!row) return;
                                e.preventDefault();
                                showMenu(
                                    e.clientX, e.clientY,
                                    row.dataset.geoid, row.dataset.name
                                );
                            });
                            document.addEventListener('click', function(e) {
                                if (!menu.contains(e.target)) hideMenu();
                            });
                            document.addEventListener('scroll', hideMenu, true);
                            window.addEventListener('resize', hideMenu);
                        })();
                    `;
                    parentDoc.head.appendChild(s);
                })();
                </script>
                """,
                height=0,
            )

    # --- Demographics tab ------------------------------------------------
    with tab_demo:
        st.subheader("Demographics vs. Risk Score")
        corr = correlation_with_risk(gdf)
        corr_df = corr.rename("Pearson r").to_frame().reset_index().rename(
            columns={"index": "Demographic"}
        )
        pretty = {v["col"]: k for k, v in OVERLAY_OPTIONS.items()}
        corr_df["Demographic"] = corr_df["Demographic"].map(pretty).fillna(
            corr_df["Demographic"]
        )
        col_chart, col_table = st.columns([2, 1])
        with col_chart:
            st.bar_chart(corr_df.set_index("Demographic"), height=280)
        with col_table:
            st.dataframe(corr_df.round(3), hide_index=True, use_container_width=True)
        st.caption(
            "Pearson correlation between each demographic and the Underservice Risk Score. "
            "Positive r → higher values coincide with higher risk."
        )

    # --- Predictor tab ---------------------------------------------------
    with tab_pred:
        st.subheader("Predict Risk Score from Demographics")
        model, metadata = load_model()
        if model is None:
            st.info(
                "Train the model first: `python -m pipeline.demographic_analysis`. "
                "Once `output/demographic_model.joblib` exists this panel activates."
            )
        else:
            st.caption(
                f"Random Forest trained on "
                f"{len(gdf.dropna(subset=metadata['features'])):,} tracts. "
                f"Held-out R² = **{metadata['r2']:.2f}**, "
                f"RMSE = **{metadata['rmse']:.1f}** points."
            )
            ranges = metadata["feature_ranges"]
            features = metadata["features"]
            inputs = {}
            pretty_label = {v["col"]: k for k, v in OVERLAY_OPTIONS.items()}
            pretty_label.setdefault("mean_commute_time", "Aggregate Commute Time")
            cols = st.columns(3)
            for i, feat in enumerate(features):
                r = ranges[feat]
                with cols[i % 3]:
                    inputs[feat] = st.slider(
                        pretty_label.get(feat, feat),
                        min_value=float(r["min"]),
                        max_value=float(r["max"]),
                        value=float(r["median"]),
                        key=f"pred_{feat}",
                    )
            X = np.array([[inputs[f] for f in features]])
            pred = float(model.predict(X)[0])
            pred_color = "#e63946" if pred >= 75 else "#f4a261" if pred >= 50 else "#2ec4b6"
            st.markdown(
                f'<div style="text-align:center;padding:16px;background:#1e1e2e;border-radius:8px;">'
                f'<div style="color:#aaa;font-size:0.8rem;text-transform:uppercase;letter-spacing:0.08em">'
                f'Predicted Risk Score</div>'
                f'<div style="color:{pred_color};font-size:3rem;font-weight:900">{pred:.1f}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            imp = pd.Series(metadata["importance"]).sort_values(ascending=True)
            imp.index = [pretty_label.get(f, f) for f in imp.index]
            st.markdown("**Feature importance**")
            st.bar_chart(imp, height=260)

    # --- Methodology tab -------------------------------------------------
    with tab_method:
        st.markdown(
            """
            ## Underservice Risk Score

            The **Underservice Risk Score** (0–100) ranks each NYC census tract on four
            independent indicators of municipal neglect, then averages their percentile ranks
            using fixed weights. A tract scoring 80 ranks in the top 20% on most dimensions.

            ### Composite inputs

            | Input | Weight | What it measures |
            |---|---|---|
            | **Accountability Gap** | 40% | HPD Class C violations ÷ 311 complaint rate. High values mean serious violations accumulate while residents don't (or can't) report them — silent neglect. |
            | **Severity-Weighted Violation Rate** | 30% | Class C violations per housing unit, multiplied by `(1 + vacate_rate)`. Distinguishes "many minor issues" from "buildings declared uninhabitable." |
            | **Average 311 Closure Time** | 20% | How long housing complaints take to close (2024–present, auto-closes excluded). Double-corrected — see below. |
            | **Vacate Order Rate** | 10% | Vacated units per housing unit. Independent severity check. |

            ### Bias corrections built into the score

            **1 — Income-adjusted complaint rate.**
            Wealthier tracts file more 311 complaints per capita (more 311 savvy, more access
            to alternatives). Without correction, high-income gentrifying tracts look
            under-neglected because their raw complaint rate inflates the denominator of the
            Accountability Gap. We residualize `complaint_rate` against `log(median_income)`
            via OLS and re-center on the citywide mean before computing the gap.

            **2 — Complaint-type normalization of closure time.**
            Heat complaints close in days; mold complaints take months. A tract dominated by
            mold complaints will have a high raw `avg_closure_time` regardless of how
            responsive the city is. We divide each complaint's closure time by the citywide
            median for its type, producing a unitless ratio (1.0 = typical for that complaint
            category). Per-tract means of this ratio are comparable across neighborhoods.

            **3 — Triage residualization of closure time.**
            HPD prioritizes high-violation buildings, so tracts with the most violations
            actually get artificially fast responses. Without correction, the worst-off tracts
            look more responsive than they are. We residualize the type-normalized closure
            ratio against `violation_rate` via OLS and re-center, so the final
            `avg_closure_time_adjusted` measures: *"is the city slower here than triage alone
            would predict?"*

            ### Why a rank composite, not regression?

            OLS on closure time alone yields R² ≈ 0.03 — closure time variance is dominated
            by unmeasured factors (complaint category mix, season, building owner).
            The rank composite avoids overfitting a weak single signal. Each tract gets a
            percentile rank on each dimension independently; the weighted average of those
            ranks is the risk score. This is interpretable by design: a score of 70 means
            the tract ranks in the top 30% on most neglect dimensions.

            ### Building-stock controls (PLUTO)

            Old buildings produce more heat, plumbing, and plaster complaints regardless of
            who lives in them. To prevent "old housing stock" from being conflated with
            "city neglect" in the demographic model, the Random Forest controlling for
            demographics also includes three PLUTO-derived building-stock features:

            - **Median year built** — unweighted median across residential lots in the tract
            - **Pre-war unit share** — fraction of residential units in buildings completed
              before 1947 (NYC Multiple Dwelling Law old-law threshold)
            - **Rent-stabilization proxy** — fraction of residential units in pre-1974
              buildings with ≥6 units (ETPA threshold; presumptively rent-stabilized)

            These are structural features of the housing stock, not demographic outcomes,
            and they're largely orthogonal to income and race in the regression.

            ### Demographic decomposition (Watchlist / Predictor tabs)

            A Random Forest (300 trees, 5-fold CV, R² = **0.748**, RMSE = **10.4 points**)
            is trained to predict the risk score from 12 demographic + building-stock features.
            The **residual** (`risk_score − RF_prediction`) is the quantity displayed in the
            Watchlist and the **Unexplained Neglect** map layer.

            **Positive residual** = a tract is *more* underserved than its demographics and
            building age predict. This is the signal of institutional neglect: the city is
            delivering worse service here than a purely structural model would expect.

            **Negative residual** = a tract outperforms its demographic prediction.

            The residual is not a correction of the risk score — it's a second lens. A tract
            can have a high risk score *and* a near-zero residual (demographics fully explain
            the neglect) or a moderate risk score with a large positive residual (neglect
            is disproportionate to what demographics would suggest). Moran's I on the
            residuals is +0.19, indicating the remaining spatial clustering is a finding
            about institutional geography, not a model artifact.

            ### Data sources

            | Dataset | Source | Coverage |
            |---|---|---|
            | 311 Service Requests | NYC Open Data | 2024–present, housing types only |
            | HPD Class C Violations | NYC Open Data | Full history |
            | HPD Vacate Orders (Order to Repair) | NYC Open Data | Full history |
            | PLUTO (Primary Land Use Tax Lot Output) | NYC Open Data / DCP | Latest release |
            | ACS 5-Year Estimates | U.S. Census Bureau | 2022 |
            | Census Tract Boundaries | NYC Planning (nyct2020.shp) | 2020 |

            ### Known limitations
            - 311 may include duplicate complaints from the same building (not deduplicated).
            - The rent-stabilization proxy (pre-1974, ≥6 units) misses 421-a opt-ins, J-51
              enrollments, and voluntary deregulations — it is a bulk approximation.
            - The demographic Random Forest is a counterfactual probe, not a causal model.
              A high residual flags a pattern worth investigating, not a proven instance of
              discrimination.
            """
        )

    # --- Jump to Map tab when watchlist triggers "Show on map" -------------
    if st.session_state.jump_to_map:
        st.session_state.jump_to_map = False
        components.html(
            """
            <script>
            (function() {
                const doc = window.parent.document;
                const parentWin = window.parent;

                // Click the Map tab (reload from ?jump= may already land here,
                // but click defensively in case a previous tab was cached).
                const tabs = doc.querySelectorAll('[data-baseweb="tab"], button[role="tab"]');
                for (const t of tabs) {
                    if ((t.innerText || '').trim().toLowerCase() === 'map') {
                        t.click();
                        break;
                    }
                }

                // Detail card is rendered after st_folium finishes, so poll briefly
                // for the element and scroll it (and the page) to the top.
                let tries = 0;
                const tick = setInterval(() => {
                    const detail = doc.querySelector('.st-key-floating-detail');
                    if (detail) {
                        detail.scrollTop = 0;
                        parentWin.scrollTo({ top: 0, behavior: 'instant' });
                        clearInterval(tick);
                    } else if (++tries > 40) {
                        clearInterval(tick);
                    }
                }, 100);
            })();
            </script>
            """,
            height=0,
        )

    # --- Make the floating filter + detail cards draggable. ------------------
    # Runs inside a 0-height component iframe but reaches the main Streamlit
    # document via `window.parent`. A MutationObserver re-attaches handlers
    # after Streamlit reruns (which replace the card DOM nodes).  A global
    # flag on window.parent prevents stacking multiple observers.
    components.html(
        """
        <script>
        (function() {
            const parentDoc = window.parent.document;
            const parentWin = window.parent;
            const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

            function makeDraggable(panel) {
                if (panel.dataset.draggable === 'true') return;
                panel.dataset.draggable = 'true';

                // Inject a dedicated drag handle at the top of the panel
                const handle = parentDoc.createElement('div');
                handle.className = 'drag-handle';
                handle.title = 'Drag to move';
                panel.prepend(handle);

                let dragging = false, offX = 0, offY = 0;

                handle.addEventListener('mousedown', (e) => {
                    dragging = true;
                    const rect = panel.getBoundingClientRect();
                    offX = e.clientX - rect.left;
                    offY = e.clientY - rect.top;
                    panel.style.userSelect = 'none';
                    panel.style.transition = 'none';
                    e.preventDefault();
                });

                parentDoc.addEventListener('mousemove', (e) => {
                    if (!dragging) return;
                    const w = panel.offsetWidth, h = panel.offsetHeight;
                    const maxX = parentWin.innerWidth - w - 10;
                    const maxY = parentWin.innerHeight - h - 10;
                    panel.style.left  = clamp(e.clientX - offX, 10, maxX) + 'px';
                    panel.style.top   = clamp(e.clientY - offY, 10, maxY) + 'px';
                    panel.style.right = 'auto';
                    panel.style.bottom = 'auto';
                });
                parentDoc.addEventListener('mouseup', () => {
                    if (!dragging) return;
                    dragging = false;
                    panel.style.userSelect = '';
                });
            }

            function scan() {
                parentDoc
                    .querySelectorAll('.st-key-floating-filters, .st-key-floating-detail')
                    .forEach(makeDraggable);
            }

            scan();
            if (!parentWin._draggablePanelsObserver) {
                const obs = new MutationObserver(scan);
                obs.observe(parentDoc.body, { childList: true, subtree: true });
                parentWin._draggablePanelsObserver = obs;
            }
        })();
        </script>
        """,
        height=0,
    )


if __name__ == "__main__":
    main()
