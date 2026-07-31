"""
One-shot migration: add `inject_theme()` + `page_header()` to every app/pages/*.py.

Idempotent — safe to re-run. Rewrites each page's top 3-4 lines so:
  - imports include `from app.utils.theme import inject_theme, page_header`
  - inject_theme() is called immediately after st.set_page_config(...)
  - the old `st.title(...)` + `st.caption(...)` pair becomes `page_header(...)`
"""
from __future__ import annotations
import re
from pathlib import Path

PAGES_DIR = Path(__file__).resolve().parents[1] / "app" / "pages"

# (title, subtitle, icon) per page — from what's currently in each file.
PAGE_META = {
    "01_Search.py":     ("Property Search",    "Type an address, parcel ID, or owner name to pull the full property profile.", "🔍"),
    "02_Leads.py":      ("Leads",              "Score and manage your entire lead pipeline.",                                  "🎯"),
    "03_Pipeline.py":   ("Deal Pipeline",      "Kanban view of every deal by stage.",                                          "📋"),
    "04_Analysis.py":   ("Deal Analysis",      "Comps, ARV, repairs, MAO, and every deal type in one place.",                  "💡"),
    "05_Buyers.py":     ("Cash Buyer Database","Filter, tag, and blast your buyer list.",                                      "💰"),
    "06_Outreach.py":   ("Owner Outreach",     "Skip-trace and contact motivated sellers.",                                    "✉️"),
    "07_Contracts.py":  ("Contracts",          "Assignment and closing document templates — always attorney-review.",          "📝"),
    "08_My_Work.py":    ("My Work",            "Live workspace for every active deal.",                                        "💼"),
    "09_Deal_Finder.py":("Deal Finder",        "Top opportunities ranked by distress score.",                                  "🔥"),
    "10_Comp_Report.py":("Comp Report",        "Printable comp reports for buyers and sellers.",                               "📊"),
}

THEME_IMPORT = "from app.utils.theme import inject_theme, page_header"


def migrate(path: Path) -> bool:
    meta = PAGE_META.get(path.name)
    if not meta:
        return False
    title, subtitle, icon = meta
    text = path.read_text(encoding="utf-8")
    orig = text

    # 1) Ensure theme import (idempotent)
    if THEME_IMPORT not in text:
        # Insert right after the first `import streamlit as st` line.
        m = re.search(r"^import streamlit as st.*$", text, flags=re.MULTILINE)
        if m:
            insert_at = m.end()
            text = text[:insert_at] + f"\n{THEME_IMPORT}" + text[insert_at:]
        else:
            text = f"{THEME_IMPORT}\n" + text

    # 2) Inject inject_theme() immediately after st.set_page_config(...)
    if "inject_theme()" not in text:
        m = re.search(r"st\.set_page_config\([^)]*\)", text, flags=re.DOTALL)
        if m:
            end = m.end()
            text = text[:end] + "\ninject_theme()" + text[end:]

    # 3) Replace the first st.title(...) with page_header(...).
    #    Also gobble a following st.caption(...) call if present.
    sub_esc = subtitle.replace('"', '\\"')
    hero_line = f'page_header("{title}", "{sub_esc}", icon="{icon}")\n'

    # Match `st.title("...")` optionally followed by `\nst.caption("...")`
    pattern = re.compile(
        r"""st\.title\(\s*(?:f?["'][^"']*["'])\s*\)\s*(?:\r?\n\s*st\.caption\(\s*(?:f?["'][^"']*["'])\s*\)\s*)?""",
        re.DOTALL,
    )
    text, n_hits = pattern.subn(hero_line, text, count=1)

    if text != orig:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed, skipped = [], []
    for py in sorted(PAGES_DIR.glob("*.py")):
        if py.name.startswith("__"):
            continue
        did = migrate(py)
        (changed if did else skipped).append(py.name)
    print(f"✔ migrated: {len(changed)}")
    for n in changed:
        print(f"    - {n}")
    if skipped:
        print(f"– skipped (already migrated or no rule): {len(skipped)}")
        for n in skipped:
            print(f"    - {n}")


if __name__ == "__main__":
    main()
