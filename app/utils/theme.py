"""
WholesaleOS Design System
─────────────────────────
One-call CSS injector + reusable UI components.

Every page should call `inject_theme()` right after `st.set_page_config()`:

    from app.utils.theme import inject_theme, page_header
    st.set_page_config(page_title="Search | WholesaleOS", layout="wide")
    inject_theme()
    page_header("🔍 Property Search", "Type an address, parcel ID, or owner name.")

Components:
    inject_theme()          — global CSS
    page_header()           — gradient page header
    kpi_card()              — big KPI number in a bordered card
    section_header()        — divider + subtitle
    pill()                  — inline status badge
    stat_row()              — horizontal stat strip
"""

from __future__ import annotations
import streamlit as st

# ── Design tokens ────────────────────────────────────────────────────────────
COLORS = {
    "bg":        "#08090d",   # page background
    "surface":   "#111319",   # card / secondary bg
    "surface2":  "#1a1d24",   # elevated card
    "border":    "#232830",   # subtle border
    "border_hi": "#3a4048",   # hover border
    "text":      "#e4e6eb",   # primary text
    "muted":     "#8b9098",   # secondary text
    "primary":   "#f97316",   # brand orange
    "primary2":  "#fb923c",   # lighter orange
    "primary_g": "linear-gradient(135deg, #f97316 0%, #dc2626 100%)",
    "success":   "#10b981",   # green (profit / positive)
    "warning":   "#f59e0b",   # amber
    "danger":    "#ef4444",   # red (loss / urgent)
    "info":      "#3b82f6",   # blue
    "cyan":      "#06b6d4",   # data highlight
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
    letter-spacing: -0.01em;
}}
.stApp {{
    background:
        radial-gradient(1200px 600px at 10% -10%, rgba(249, 115, 22, 0.10) 0%, transparent 60%),
        radial-gradient(900px 500px at 110% 10%, rgba(59, 130, 246, 0.06) 0%, transparent 55%),
        {COLORS['bg']};
}}

/* Numbers use tabular font */
[data-testid="stMetricValue"], .kpi-value, .mono {{
    font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace !important;
    font-feature-settings: 'tnum' 1, 'zero' 1;
}}

/* ── Headings ───────────────────────────────────────────────────── */
h1, h2, h3, h4, h5, h6 {{
    font-family: 'Inter', sans-serif !important;
    letter-spacing: -0.02em;
    font-weight: 700 !important;
}}
h1 {{ font-weight: 800 !important; }}

/* ── Sidebar ────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {COLORS['surface']} 0%, {COLORS['bg']} 100%) !important;
    border-right: 1px solid {COLORS['border']};
}}
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] a {{
    font-weight: 500;
    border-radius: 8px;
    transition: all 0.15s ease;
}}
section[data-testid="stSidebar"] a:hover {{
    background: {COLORS['surface2']} !important;
    color: {COLORS['primary2']} !important;
    transform: translateX(2px);
}}

/* ── Metrics ────────────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    padding: 16px 18px;
    transition: all 0.2s ease;
}}
[data-testid="stMetric"]:hover {{
    border-color: {COLORS['border_hi']};
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(0,0,0,0.35);
}}
[data-testid="stMetricLabel"] p {{
    color: {COLORS['muted']} !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
[data-testid="stMetricValue"] {{
    color: {COLORS['text']} !important;
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
}}
[data-testid="stMetricDelta"] {{
    font-size: 0.8rem !important;
    font-weight: 600 !important;
}}

/* ── Buttons ────────────────────────────────────────────────────── */
.stButton > button {{
    border-radius: 10px !important;
    border: 1px solid {COLORS['border']} !important;
    background: {COLORS['surface']} !important;
    color: {COLORS['text']} !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
    padding: 0.5rem 1rem !important;
    transition: all 0.15s ease !important;
}}
.stButton > button:hover {{
    background: {COLORS['surface2']} !important;
    border-color: {COLORS['primary']} !important;
    color: {COLORS['primary2']} !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 14px rgba(249, 115, 22, 0.15);
}}
.stButton > button[kind="primary"] {{
    background: {COLORS['primary_g']} !important;
    border: none !important;
    color: white !important;
    box-shadow: 0 4px 14px rgba(249, 115, 22, 0.35);
}}
.stButton > button[kind="primary"]:hover {{
    filter: brightness(1.1);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(249, 115, 22, 0.5);
}}

/* ── Inputs ─────────────────────────────────────────────────────── */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
.stSelectbox div[data-baseweb="select"] > div,
.stDateInput input {{
    background: {COLORS['surface']} !important;
    border: 1px solid {COLORS['border']} !important;
    border-radius: 10px !important;
    color: {COLORS['text']} !important;
    transition: all 0.15s ease;
}}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {{
    border-color: {COLORS['primary']} !important;
    box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.15) !important;
}}

/* ── Tabs ───────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background: {COLORS['surface']};
    padding: 6px;
    border-radius: 12px;
    border: 1px solid {COLORS['border']};
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
    box-shadow: 0 2px 8px rgba(249, 115, 22, 0.35);
}}

/* ── Expander ───────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']} !important;
    border-radius: 12px !important;
    overflow: hidden;
}}
[data-testid="stExpander"] summary {{
    font-weight: 600 !important;
    color: {COLORS['text']} !important;
    padding: 12px 16px !important;
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
    overflow: hidden;
}}

/* ── Info / Success / Warning / Error boxes ─────────────────────── */
[data-testid="stAlert"] {{
    border-radius: 12px !important;
    border: 1px solid {COLORS['border']} !important;
    padding: 14px 18px !important;
}}
[data-testid="stAlert"][data-baseweb="notification"] {{ border-left-width: 4px !important; }}

/* ── Bordered container ─────────────────────────────────────────── */
[data-testid="stContainer"][class*="st-"] {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
}}

/* ── Slider ─────────────────────────────────────────────────────── */
.stSlider [data-baseweb="slider"] div[role="slider"] {{
    background: {COLORS['primary']} !important;
    border: 3px solid white !important;
    box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.25) !important;
}}

/* ── Radio ──────────────────────────────────────────────────────── */
.stRadio > div {{ gap: 6px !important; }}

/* ── Progress bar ───────────────────────────────────────────────── */
.stProgress > div > div > div {{
    background: {COLORS['primary_g']} !important;
    border-radius: 4px;
}}

/* ── Caption ────────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] {{
    color: {COLORS['muted']} !important;
    font-size: 0.82rem !important;
}}

/* ── Custom design-system classes ───────────────────────────────── */
.ws-hero {{
    background: linear-gradient(135deg, {COLORS['surface']} 0%, {COLORS['surface2']} 100%);
    border: 1px solid {COLORS['border']};
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 20px;
    position: relative;
    overflow: hidden;
}}
.ws-hero::before {{
    content: '';
    position: absolute;
    top: 0; right: 0;
    width: 300px; height: 100%;
    background: radial-gradient(circle at 90% 50%, rgba(249, 115, 22, 0.18) 0%, transparent 70%);
    pointer-events: none;
}}
.ws-hero h1 {{
    margin: 0 !important;
    font-size: 2.1rem !important;
    background: linear-gradient(135deg, #fff 0%, #f97316 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.ws-hero p {{
    margin: 6px 0 0 0 !important;
    color: {COLORS['muted']};
    font-size: 1rem;
}}

.ws-kpi {{
    background: linear-gradient(135deg, {COLORS['surface']} 0%, {COLORS['surface2']} 100%);
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
    padding: 18px 20px;
    height: 100%;
    transition: all 0.2s ease;
    position: relative;
    overflow: hidden;
}}
.ws-kpi:hover {{
    border-color: {COLORS['primary']};
    transform: translateY(-2px);
    box-shadow: 0 10px 30px rgba(249, 115, 22, 0.15);
}}
.ws-kpi::after {{
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: {COLORS['primary_g']};
}}
.ws-kpi-label {{
    color: {COLORS['muted']};
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}}
.ws-kpi-value {{
    color: {COLORS['text']};
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.75rem;
    font-weight: 700;
    line-height: 1.2;
}}
.ws-kpi-delta {{
    color: {COLORS['muted']};
    font-size: 0.78rem;
    margin-top: 4px;
    font-weight: 500;
}}
.ws-kpi-delta.up {{ color: {COLORS['success']}; }}
.ws-kpi-delta.down {{ color: {COLORS['danger']}; }}

.ws-section {{
    color: {COLORS['muted']};
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin: 24px 0 10px 0;
    display: flex;
    align-items: center;
    gap: 10px;
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
    font-weight: 600;
    letter-spacing: 0.02em;
    border: 1px solid;
    margin-right: 6px;
}}
.ws-pill.success {{ color: {COLORS['success']}; background: rgba(16,185,129,0.10); border-color: rgba(16,185,129,0.35); }}
.ws-pill.warning {{ color: {COLORS['warning']}; background: rgba(245,158,11,0.10); border-color: rgba(245,158,11,0.35); }}
.ws-pill.danger  {{ color: {COLORS['danger']};  background: rgba(239,68,68,0.10);  border-color: rgba(239,68,68,0.35); }}
.ws-pill.info    {{ color: {COLORS['info']};    background: rgba(59,130,246,0.10); border-color: rgba(59,130,246,0.35); }}
.ws-pill.brand   {{ color: {COLORS['primary2']}; background: rgba(249,115,22,0.10); border-color: rgba(249,115,22,0.35); }}

/* Hide Streamlit chrome we don't want */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
.stDeployButton {{ display: none; }}

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
    """Render a gradient hero header at the top of a page."""
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
    """Render a single KPI card. Use inside `st.columns(...)`.

    direction: '' | 'up' | 'down' — colours the delta green / red.
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
    """Render a small uppercase section separator."""
    st.markdown(f'<div class="ws-section">{label}</div>', unsafe_allow_html=True)


def pill(text: str, kind: str = "brand") -> str:
    """Return HTML for an inline status pill. Use inside `st.markdown(..., unsafe_allow_html=True)`.

    kind: 'brand' | 'success' | 'warning' | 'danger' | 'info'
    """
    return f'<span class="ws-pill {kind}">{text}</span>'


def stat_row(stats: list[tuple[str, str]]) -> None:
    """Render a horizontal strip of small stats: [(label, value), ...]."""
    cols = st.columns(len(stats))
    for col, (label, value) in zip(cols, stats):
        with col:
            kpi_card(label, value)
