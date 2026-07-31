"""
WholesaleOS Design System — Light Theme
────────────────────────────────────────
Premium fintech-style light UI: warm off-white background, pure-white cards,
deep-navy text, brand-orange accents, teal for money.

Every page should call `inject_theme()` right after `st.set_page_config()`:

    from app.utils.theme import inject_theme, page_header
    st.set_page_config(page_title="Search | WholesaleOS", layout="wide")
    inject_theme()
    page_header("🔍 Property Search", "Type an address or parcel ID.")

Components:
    inject_theme()          — global CSS
    page_header()           — gradient hero header
    kpi_card()              — big KPI number card
    section_header()        — small uppercase divider
    pill()                  — inline status badge
    stat_row()              — horizontal strip of KPIs
"""

from __future__ import annotations
import streamlit as st

# ── Design tokens ────────────────────────────────────────────────────────────
COLORS = {
    "bg":         "#fafaf9",   # warm off-white page background
    "surface":    "#ffffff",   # pure white cards
    "surface2":   "#f5f5f4",   # subtle-tint elevated surface
    "border":     "#e7e5e4",   # warm gray border
    "border_hi":  "#d6d3d1",   # hover border
    "text":       "#0f172a",   # deep navy primary text
    "text2":      "#1e293b",   # slightly softer heading
    "muted":      "#64748b",   # secondary text
    "muted2":     "#94a3b8",   # tertiary text
    "primary":    "#ea580c",   # brand orange
    "primary2":   "#f97316",   # lighter orange
    "primary_g":  "linear-gradient(135deg, #ea580c 0%, #dc2626 100%)",
    "success":    "#059669",   # money-in green
    "success_bg": "#ecfdf5",
    "warning":    "#d97706",   # amber warning
    "warning_bg": "#fffbeb",
    "danger":     "#dc2626",   # money-out red
    "danger_bg":  "#fef2f2",
    "info":       "#0284c7",   # info blue
    "info_bg":    "#f0f9ff",
    "teal":       "#0f766e",   # money highlight
    "shadow_sm":  "0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04)",
    "shadow_md":  "0 4px 12px rgba(15, 23, 42, 0.08), 0 2px 4px rgba(15, 23, 42, 0.04)",
    "shadow_lg":  "0 12px 32px rgba(15, 23, 42, 0.12), 0 4px 8px rgba(15, 23, 42, 0.06)",
    "shadow_brand": "0 6px 20px rgba(234, 88, 12, 0.28)",
}


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL CSS INJECTION
# ═══════════════════════════════════════════════════════════════════════════
def inject_theme() -> None:
    """Inject the WholesaleOS design system CSS. Call once per page."""
    st.markdown(
        f"""
<style>
/* ── Google Fonts ────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap');

/* ── Root & base ────────────────────────────────────────────────── */
html, body, [class*="css"], .stApp {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    letter-spacing: -0.011em;
    color: {COLORS['text']};
}}
.stApp {{
    background:
        radial-gradient(1400px 700px at 8% -12%, rgba(234, 88, 12, 0.08) 0%, transparent 55%),
        radial-gradient(1000px 500px at 115% 8%, rgba(2, 132, 199, 0.05) 0%, transparent 55%),
        {COLORS['bg']};
}}

/* Numbers use tabular font */
[data-testid="stMetricValue"], .kpi-value, .mono {{
    font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace !important;
    font-feature-settings: 'tnum' 1, 'zero' 1;
    letter-spacing: -0.015em;
}}

/* ── Headings ───────────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {{
    font-family: 'Inter', sans-serif !important;
    letter-spacing: -0.025em;
    font-weight: 700 !important;
    color: {COLORS['text']};
}}
h1 {{ font-weight: 800 !important; }}

/* ── Sidebar ────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background: {COLORS['surface']} !important;
    border-right: 1px solid {COLORS['border']};
    box-shadow: 4px 0 24px rgba(15, 23, 42, 0.03);
}}
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] a {{
    font-weight: 500;
    border-radius: 8px;
    transition: all 0.15s ease;
    color: {COLORS['text']} !important;
}}
section[data-testid="stSidebar"] a:hover {{
    background: {COLORS['surface2']} !important;
    color: {COLORS['primary']} !important;
    transform: translateX(2px);
}}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: linear-gradient(90deg, rgba(234, 88, 12, 0.10), transparent) !important;
    color: {COLORS['primary']} !important;
    border-left: 3px solid {COLORS['primary']};
    padding-left: 12px !important;
    font-weight: 600 !important;
}}

/* ── Metrics ────────────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
    padding: 18px 20px;
    box-shadow: {COLORS['shadow_sm']};
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}}
[data-testid="stMetric"]:hover {{
    border-color: {COLORS['border_hi']};
    transform: translateY(-2px);
    box-shadow: {COLORS['shadow_md']};
}}
[data-testid="stMetricLabel"] p {{
    color: {COLORS['muted']} !important;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}}
[data-testid="stMetricValue"] {{
    color: {COLORS['text']} !important;
    font-size: 1.9rem !important;
    font-weight: 700 !important;
    line-height: 1.15 !important;
    margin-top: 4px;
}}
[data-testid="stMetricDelta"] {{
    font-size: 0.82rem !important;
    font-weight: 600 !important;
}}

/* ── Buttons ────────────────────────────────────────────────────── */
.stButton > button {{
    border-radius: 10px !important;
    border: 1px solid {COLORS['border']} !important;
    background: {COLORS['surface']} !important;
    color: {COLORS['text']} !important;
    font-weight: 600 !important;
    letter-spacing: -0.005em;
    padding: 0.55rem 1.05rem !important;
    box-shadow: {COLORS['shadow_sm']};
    transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1) !important;
}}
.stButton > button:hover {{
    background: {COLORS['surface2']} !important;
    border-color: {COLORS['primary']} !important;
    color: {COLORS['primary']} !important;
    transform: translateY(-1px);
    box-shadow: {COLORS['shadow_md']};
}}
.stButton > button[kind="primary"] {{
    background: {COLORS['primary_g']} !important;
    border: none !important;
    color: white !important;
    box-shadow: {COLORS['shadow_brand']};
}}
.stButton > button[kind="primary"]:hover {{
    filter: brightness(1.08);
    transform: translateY(-2px);
    box-shadow: 0 12px 28px rgba(234, 88, 12, 0.42);
    color: white !important;
}}
.stDownloadButton > button {{
    border-radius: 10px !important;
    background: {COLORS['surface']} !important;
    border: 1px solid {COLORS['border']} !important;
    font-weight: 600 !important;
}}

/* ── Inputs ─────────────────────────────────────────────────────── */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
.stSelectbox div[data-baseweb="select"] > div,
.stMultiSelect div[data-baseweb="select"] > div,
.stDateInput input {{
    background: {COLORS['surface']} !important;
    border: 1px solid {COLORS['border']} !important;
    border-radius: 10px !important;
    color: {COLORS['text']} !important;
    box-shadow: {COLORS['shadow_sm']};
    transition: all 0.15s ease;
}}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {{
    border-color: {COLORS['primary']} !important;
    box-shadow: 0 0 0 3px rgba(234, 88, 12, 0.12) !important;
    outline: none;
}}
label, .stTextInput label, .stNumberInput label, .stSelectbox label, .stMultiSelect label {{
    font-weight: 600 !important;
    color: {COLORS['text2']} !important;
    font-size: 0.86rem !important;
}}

/* ── Tabs ───────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: {COLORS['surface']};
    padding: 6px;
    border-radius: 12px;
    border: 1px solid {COLORS['border']};
    box-shadow: {COLORS['shadow_sm']};
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {COLORS['muted']} !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 8px 16px !important;
    border: none !important;
    transition: all 0.15s ease;
}}
.stTabs [data-baseweb="tab"]:hover {{
    background: {COLORS['surface2']} !important;
    color: {COLORS['text']} !important;
}}
.stTabs [aria-selected="true"] {{
    background: {COLORS['primary_g']} !important;
    color: white !important;
    box-shadow: {COLORS['shadow_brand']};
}}

/* ── Expander ───────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']} !important;
    border-radius: 12px !important;
    box-shadow: {COLORS['shadow_sm']};
    overflow: hidden;
}}
[data-testid="stExpander"] summary {{
    font-weight: 600 !important;
    color: {COLORS['text']} !important;
    padding: 14px 18px !important;
}}
[data-testid="stExpander"] summary:hover {{
    background: {COLORS['surface2']};
}}

/* ── Divider ────────────────────────────────────────────────────── */
hr {{
    border-color: {COLORS['border']} !important;
    margin: 1.5rem 0 !important;
}}

/* ── DataFrame ──────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {{
    border-radius: 12px;
    border: 1px solid {COLORS['border']};
    box-shadow: {COLORS['shadow_sm']};
    overflow: hidden;
}}
[data-testid="stDataFrame"] thead {{
    background: {COLORS['surface2']} !important;
}}

/* ── Alerts ─────────────────────────────────────────────────────── */
[data-testid="stAlert"] {{
    border-radius: 12px !important;
    border: 1px solid {COLORS['border']} !important;
    padding: 14px 18px !important;
    box-shadow: {COLORS['shadow_sm']};
}}

/* ── Bordered container ─────────────────────────────────────────── */
[data-testid="stContainer"][class*="st-"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
    box-shadow: {COLORS['shadow_sm']};
}}

/* ── Slider ─────────────────────────────────────────────────────── */
.stSlider [data-baseweb="slider"] div[role="slider"] {{
    background: {COLORS['primary']} !important;
    border: 3px solid white !important;
    box-shadow: 0 0 0 4px rgba(234, 88, 12, 0.20), {COLORS['shadow_sm']} !important;
}}
.stSlider [data-baseweb="slider"] > div > div {{
    background: {COLORS['primary_g']} !important;
}}

/* ── Radio ──────────────────────────────────────────────────────── */
.stRadio > div {{ gap: 6px !important; }}
.stRadio label {{ font-weight: 500 !important; color: {COLORS['text']} !important; }}

/* ── Progress bar ───────────────────────────────────────────────── */
.stProgress > div > div > div {{
    background: {COLORS['primary_g']} !important;
    border-radius: 4px;
}}
.stProgress > div {{ background: {COLORS['border']} !important; border-radius: 4px; }}

/* ── Caption ────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"], .stCaption {{
    color: {COLORS['muted']} !important;
    font-size: 0.82rem !important;
}}

/* ── Code blocks ────────────────────────────────────────────────── */
code {{
    background: {COLORS['surface2']} !important;
    color: {COLORS['primary']} !important;
    padding: 2px 6px !important;
    border-radius: 4px !important;
    font-size: 0.9em !important;
}}

/* ── Custom design-system classes ───────────────────────────────── */
.ws-hero {{
    background: linear-gradient(135deg, {COLORS['surface']} 0%, {COLORS['surface2']} 100%);
    border: 1px solid {COLORS['border']};
    border-radius: 20px;
    padding: 32px 36px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
    box-shadow: {COLORS['shadow_md']};
}}
.ws-hero::before {{
    content: '';
    position: absolute;
    top: 0; right: 0;
    width: 400px; height: 100%;
    background: radial-gradient(circle at 88% 50%, rgba(234, 88, 12, 0.14) 0%, transparent 65%);
    pointer-events: none;
}}
.ws-hero::after {{
    content: '';
    position: absolute;
    top: -1px; left: 0; right: 0;
    height: 3px;
    background: {COLORS['primary_g']};
    border-radius: 20px 20px 0 0;
}}
.ws-hero h1 {{
    margin: 0 !important;
    font-size: 2.3rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.035em !important;
    background: linear-gradient(135deg, {COLORS['text']} 0%, {COLORS['primary']} 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.1;
}}
.ws-hero p {{
    margin: 8px 0 0 0 !important;
    color: {COLORS['muted']};
    font-size: 1.05rem;
    font-weight: 500;
    max-width: 640px;
}}

.ws-kpi {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 16px;
    padding: 22px 24px;
    height: 100%;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
    box-shadow: {COLORS['shadow_sm']};
}}
.ws-kpi:hover {{
    border-color: {COLORS['border_hi']};
    transform: translateY(-3px);
    box-shadow: {COLORS['shadow_lg']};
}}
.ws-kpi::before {{
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 3px;
    background: {COLORS['primary_g']};
    opacity: 0.8;
}}
.ws-kpi-label {{
    color: {COLORS['muted']};
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    margin-bottom: 8px;
}}
.ws-kpi-value {{
    color: {COLORS['text']};
    font-family: 'JetBrains Mono', monospace;
    font-size: 2rem;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: -0.02em;
}}
.ws-kpi-delta {{
    color: {COLORS['muted']};
    font-size: 0.8rem;
    margin-top: 6px;
    font-weight: 500;
}}
.ws-kpi-delta.up {{ color: {COLORS['success']}; }}
.ws-kpi-delta.down {{ color: {COLORS['danger']}; }}

.ws-section {{
    color: {COLORS['muted']};
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    margin: 32px 0 14px 0;
    display: flex;
    align-items: center;
    gap: 12px;
}}
.ws-section::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, {COLORS['border']} 0%, transparent 100%);
}}

.ws-pill {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    border: 1px solid;
    margin-right: 6px;
    line-height: 1.4;
}}
.ws-pill.success {{ color: {COLORS['success']}; background: {COLORS['success_bg']}; border-color: rgba(5,150,105,0.30); }}
.ws-pill.warning {{ color: {COLORS['warning']}; background: {COLORS['warning_bg']}; border-color: rgba(217,119,6,0.30); }}
.ws-pill.danger  {{ color: {COLORS['danger']};  background: {COLORS['danger_bg']};  border-color: rgba(220,38,38,0.30); }}
.ws-pill.info    {{ color: {COLORS['info']};    background: {COLORS['info_bg']};    border-color: rgba(2,132,199,0.30); }}
.ws-pill.brand   {{ color: {COLORS['primary']}; background: rgba(234,88,12,0.08);   border-color: rgba(234,88,12,0.28); }}

.ws-card {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
    padding: 20px 22px;
    box-shadow: {COLORS['shadow_sm']};
    transition: all 0.2s ease;
    height: 100%;
}}
.ws-card:hover {{
    border-color: {COLORS['border_hi']};
    box-shadow: {COLORS['shadow_md']};
    transform: translateY(-2px);
}}
.ws-card-icon {{
    font-size: 1.75rem;
    line-height: 1;
    margin-bottom: 10px;
}}
.ws-card-title {{
    font-weight: 700;
    font-size: 1.05rem;
    color: {COLORS['text']};
    margin-bottom: 6px;
    letter-spacing: -0.01em;
}}
.ws-card-desc {{
    color: {COLORS['muted']};
    font-size: 0.88rem;
    line-height: 1.5;
    min-height: 42px;
}}

/* Hide Streamlit chrome */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
.stDeployButton {{ display: none; }}
[data-testid="stStatusWidget"] {{ display: none; }}

/* Smoother scrollbar */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: {COLORS['bg']}; }}
::-webkit-scrollbar-thumb {{ background: {COLORS['border']}; border-radius: 6px; }}
::-webkit-scrollbar-thumb:hover {{ background: {COLORS['border_hi']}; }}
</style>
        """,
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════
def page_header(title: str, subtitle: str = "", icon: str = "") -> None:
    """Gradient hero header at the top of a page."""
    icon_html = f"{icon} " if icon else ""
    st.markdown(
        f"""
<div class="ws-hero">
    <h1>{icon_html}{title}</h1>
    {f'<p>{subtitle}</p>' if subtitle else ''}
</div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, delta: str | None = None, direction: str = "") -> None:
    """One KPI card. Use inside `st.columns(...)`.

    direction: '' | 'up' | 'down' — colors the delta green / red.
    """
    delta_html = f'<div class="ws-kpi-delta {direction}">{delta}</div>' if delta else ""
    st.markdown(
        f"""
<div class="ws-kpi">
    <div class="ws-kpi-label">{label}</div>
    <div class="ws-kpi-value">{value}</div>
    {delta_html}
</div>
        """,
        unsafe_allow_html=True,
    )


def section_header(label: str) -> None:
    """Small uppercase section separator."""
    st.markdown(f'<div class="ws-section">{label}</div>', unsafe_allow_html=True)


def pill(text: str, kind: str = "brand") -> str:
    """Inline status pill HTML.

    kind: 'brand' | 'success' | 'warning' | 'danger' | 'info'
    """
    return f'<span class="ws-pill {kind}">{text}</span>'


def stat_row(stats: list[tuple[str, str]]) -> None:
    """Horizontal strip of small stats: [(label, value), ...]."""
    cols = st.columns(len(stats))
    for col, (label, value) in zip(cols, stats):
        with col:
            kpi_card(label, value)
