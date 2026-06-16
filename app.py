"""AI Trading-Card Lister & Pricer — Streamlit UI.

A photo of a card goes in; an eBay-ready title + description and a market-based
valuation come out, backed by *real* sold comps from 130point and (optionally)
active comps from eBay's Browse API. Every analysis can be saved to a local
history you can revisit.

This is a rewrite of the original prototype, which fabricated all of its data.
The business logic lives in the ``tcg`` package; this file is presentation only.
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from tcg import storage
from tcg.card_ai import AIError, AIUnavailable, identify_card
from tcg.config import load_settings
from tcg.images import ImageError, encode_jpeg, load_image, thumbnail_bytes
from tcg.models import CardIdentity, GeneratedListing, PriceReport
from tcg.pricing import PricingEngine
from tcg.psa import PsaError, PsaSource, PsaUnavailable
from tcg.sources import EbaySource, OnePointSource

st.set_page_config(page_title="AI Card Lister & Pricer", page_icon="🃏", layout="wide")

SETTINGS = load_settings()
storage.init_db(SETTINGS.db_path)

# Defensive reads for Ollama attrs — guards against a stale tcg/config.pyc on
# Streamlit Cloud where app.py may be newer than the cached module bytecode.
_OLLAMA_ENABLED: bool = getattr(SETTINGS, "ollama_enabled", False)
_OLLAMA_MODEL: str = getattr(SETTINGS, "ollama_model", "qwen2.5vl:7b")
_PSA_ENABLED: bool = getattr(SETTINGS, "psa_enabled", False)


# --------------------------------------------------------------------------- #
# cached data access
# --------------------------------------------------------------------------- #
def _build_engine() -> PricingEngine:
    onepoint = OnePointSource(timeout=SETTINGS.http_timeout, user_agent=SETTINGS.user_agent)
    ebay = EbaySource(
        client_id=SETTINGS.ebay_client_id,
        client_secret=SETTINGS.ebay_client_secret,
        env=SETTINGS.ebay_env,
        marketplace=SETTINGS.ebay_marketplace,
        timeout=SETTINGS.http_timeout,
    )
    return PricingEngine(onepoint=onepoint, ebay=ebay, comp_limit=SETTINGS.comp_limit)


@st.cache_data(ttl=900, show_spinner=False)
def fetch_report(query: str, recency_days: int | None) -> dict:
    """Cached live fetch. Returns a plain dict (cacheable & serializable)."""
    return _build_engine().build_report(query, recency_days=recency_days).to_dict()


# --------------------------------------------------------------------------- #
# small render helpers
# --------------------------------------------------------------------------- #
_CONF_COLOR = {"high": "🟢", "medium": "🟡", "low": "🟠", "none": "⚪️"}


def provenance_badges(sources: list[str]) -> str:
    if not sources:
        return "⚪️ no data"
    out = []
    for s in sources:
        low = s.lower()
        if "demo" in low or "sim" in low:   # case-insensitive; catches source='demo'
            out.append(f"🟥 {s}")
        else:
            out.append(f"🟩 {s}")
    return "  ·  ".join(out)


def sold_chart_df(
    sold: list[dict],
    currency: str | None = None,
    recency_days: int | None = None,
) -> pd.DataFrame | None:
    """Build the trend series, mirroring the valuation's currency + recency window
    so the chart can't contradict the headline numbers shown above it."""
    cutoff = (
        pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=recency_days)
        if recency_days else None
    )
    rows = []
    for c in sold:
        if not (c.get("sale_date") and c.get("price")):
            continue
        if currency and c.get("currency", "USD") != currency:
            continue
        when = pd.to_datetime(c["sale_date"], utc=True, errors="coerce")
        if pd.isna(when) or (cutoff is not None and when < cutoff):
            continue
        rows.append({"date": when, "price": c["price"]})
    if len(rows) < 2:
        return None
    df = pd.DataFrame(rows).sort_values("date")
    return df.set_index("date")[["price"]]


def comps_table(comps: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": (c.get("sale_date") or "")[:10],
                "Title": c.get("title", ""),
                "Type": c.get("sale_kind", ""),
                "Price": f"{c.get('currency', 'USD')} {c.get('price', 0):,.2f}",
                "Link": c.get("url", ""),
            }
            for c in comps
        ]
    )


def reset_card_state() -> None:
    for key in ("pil", "identity", "listing", "query", "report",
                "report_recency", "saved_id", "upload_key", "auto_done_for",
                "ai_error", "reidentify_pending", "refresh_comps_pending",
                "f_title", "f_desc", "f_cond",
                "psa_cert", "psa_error", "verify_cert_pending"):
        st.session_state.pop(key, None)


def render_psa_panel(cert: dict) -> None:
    """Show a verified PSA slab: identity, grade, and population context."""
    num = f" #{cert['card_number']}" if cert.get("card_number") else ""
    variety = f" · {cert['variety']}" if cert.get("variety") else ""
    st.success(
        f"🔖 **PSA verified** — cert #{cert.get('cert_number', '')}\n\n"
        f"**{cert.get('year', '')} {cert.get('brand', '')}**\n\n"
        f"{cert.get('subject', '')}{num}{variety} — grade **{cert.get('grade', '')}**"
    )
    higher = cert.get("population_higher")
    bits = []
    if cert.get("total_population") is not None:
        bits.append(f"{cert['total_population']:,} at this grade")
    if higher is not None:
        bits.append(f"{higher:,} graded higher")
    if bits:
        tail = ""
        if (higher or 0) >= 200:
            tail = " — abundant higher-grade supply caps this grade's value"
        elif higher is not None and higher <= 10:
            tail = " — very few graded higher; scarce in top grades"
        st.caption("PSA population: " + " · ".join(bits) + tail)


# --------------------------------------------------------------------------- #
# header
# --------------------------------------------------------------------------- #
st.title("🃏 AI Trading-Card Lister & Pricer")
if SETTINGS.anthropic_api_key:
    ai_state = f"🟢 Claude ({SETTINGS.anthropic_model})"
elif _OLLAMA_ENABLED:
    ai_state = f"🟢 Ollama ({_OLLAMA_MODEL})"
else:
    ai_state = "⚪️ off (manual entry)"
ebay_state = "🟢 on" if SETTINGS.ebay_enabled else "⚪️ off"
psa_state = "🟢 on" if _PSA_ENABLED else "⚪️ off"
st.caption(
    f"AI identification: **{ai_state}**  ·  Sold comps (130point): **🟢 live**  ·  "
    f"eBay active comps: **{ebay_state}**  ·  PSA slab verify: **{psa_state}**"
)

tab_analyze, tab_history, tab_about = st.tabs(
    ["🔎 Analyze", f"🕘 History ({storage.count_submissions(SETTINGS.db_path)})", "⚙️ Settings & About"]
)

# =========================================================================== #
# ANALYZE
# =========================================================================== #
with tab_analyze:
    # Friendly label for whichever AI engine is active this session.
    if SETTINGS.anthropic_api_key:
        _engine_label = f"Claude ({SETTINGS.anthropic_model})"
    elif _OLLAMA_ENABLED:
        _engine_label = f"Ollama ({_OLLAMA_MODEL})"
    else:
        _engine_label = None

    left, right = st.columns([1, 1.25], gap="large")

    with left:
        st.subheader("1 · Upload a card")
        uploaded = st.file_uploader(
            "Card image (front)",
            type=["jpg", "jpeg", "png", "webp", "heic", "heif"],
        )

        auto_analyze = st.checkbox(
            "⚡ Auto-analyze on upload",
            value=True,
            key="auto_analyze",
            disabled=not SETTINGS.ai_enabled,
            help="As soon as you upload, the card is identified, a listing is "
                 "drafted, and live comps + a price are pulled — no extra clicks.",
        )

        recency_label = st.selectbox(
            "Comp window",
            ["All time", "Last 30 days", "Last 90 days", "Last 180 days", "Last 365 days"],
            index=2, key="recency_label",
        )
        recency = {
            "All time": None, "Last 30 days": 30, "Last 90 days": 90,
            "Last 180 days": 180, "Last 365 days": 365,
        }[recency_label]

        # ---- new upload: load the image, arm the auto pipeline ----
        if uploaded is not None:
            key = (uploaded.name, uploaded.size)
            if st.session_state.get("upload_key") != key:
                reset_card_state()
                st.session_state.upload_key = key
                data = uploaded.getvalue()
                if len(data) > SETTINGS.max_upload_mb * 1024 * 1024:
                    st.error(f"File is larger than {SETTINGS.max_upload_mb} MB.")
                else:
                    try:
                        st.session_state.pil = load_image(
                            data, max_pixels=SETTINGS.max_image_pixels
                        )
                    except ImageError as exc:
                        st.error(f"Could not read image: {exc}")

        # ---- pipeline (runs BEFORE the query/title widgets so we can safely
        #      write their session_state values without Streamlit complaining) ----
        _run_identify = False
        _run_comps = False
        _have_img = st.session_state.get("pil") is not None

        if _have_img and SETTINGS.ai_enabled:
            if st.session_state.pop("reidentify_pending", False):
                _run_identify = True
            elif (auto_analyze
                  and st.session_state.get("auto_done_for") != st.session_state.get("upload_key")):
                _run_identify = True
                # Mark immediately so a later rerun never re-bills the same image.
                st.session_state.auto_done_for = st.session_state.get("upload_key")

        if _run_identify:
            st.session_state.pop("ai_error", None)
            with st.spinner(f"🤖 {_engine_label} is reading the card…"):
                try:
                    identity, listing = identify_card(st.session_state.pil, SETTINGS)
                    st.session_state.identity = identity
                    st.session_state.listing = listing
                    st.session_state.query = listing.search_query or ""
                    st.session_state.f_title = listing.ebay_title or ""
                    st.session_state.f_desc = listing.description or ""
                    st.session_state.f_cond = listing.suggested_condition or "Raw"
                    st.session_state.pop("report", None)
                    st.session_state.pop("saved_id", None)
                    if (st.session_state.query or "").strip():
                        _run_comps = True            # chain straight into pricing
                except AIUnavailable:
                    st.session_state.ai_error = (
                        "AI is not configured — type the card details below to pull comps."
                    )
                except AIError as exc:
                    st.session_state.ai_error = str(exc)

        if st.session_state.pop("refresh_comps_pending", False):
            _run_comps = True

        # ---- PSA slab verification (graded cards) — drives a grade-specific query ----
        if st.session_state.pop("verify_cert_pending", False):
            st.session_state.pop("psa_error", None)
            cert_raw = (st.session_state.get("cert_input") or "").strip()
            with st.spinner("🔖 Verifying PSA cert…"):
                try:
                    psa_cert = PsaSource(SETTINGS).verify_cert(cert_raw)
                    st.session_state.psa_cert = psa_cert.to_dict()
                    st.session_state.query = psa_cert.search_query()
                    st.session_state.pop("saved_id", None)
                    # Seed copy-ready fields from the slab (only if AI hasn't
                    # already filled them — setdefault never clobbers).
                    st.session_state.setdefault("f_title", psa_cert.listing_title())
                    st.session_state.setdefault("f_desc", psa_cert.listing_description())
                    st.session_state["f_cond"] = psa_cert.condition
                    _run_comps = True              # chain into grade-specific pricing
                except (PsaError, PsaUnavailable) as exc:
                    st.session_state.psa_error = str(exc)
                    st.session_state.pop("psa_cert", None)

        if _run_comps:
            q = (st.session_state.get("query") or "").strip()
            if q:
                with st.spinner(f"📈 Pulling 130point sold comps for “{q}”…"):
                    try:
                        st.session_state.report = fetch_report(q, recency)
                        st.session_state.report_recency = recency
                        st.session_state.pop("saved_id", None)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Comp lookup failed: {exc}")

        # ---- image preview ----
        if _have_img:
            st.image(st.session_state.pil, caption="Uploaded card", use_container_width=True)

        if st.session_state.get("ai_error"):
            st.warning(st.session_state["ai_error"])

        # Backend caveat: Ollama must be reachable from wherever the app runs.
        if SETTINGS.ai_enabled and not SETTINGS.anthropic_api_key:
            st.caption(
                "ℹ️ Ollama runs **locally** — on a hosted server (e.g. Streamlit "
                "Cloud) it must be reachable from there, or identification will fail."
            )
        elif not SETTINGS.ai_enabled:
            st.info(
                "AI identification is off. Type the card below to pull real comps, "
                "or enable it in **Settings & About**."
            )

        # ---- query + manual controls ----
        st.text_input(
            "Search query for comps",
            key="query",
            placeholder="e.g. 2018 Topps Chrome Shohei Ohtani Rookie",
            help="What we search on 130point / eBay. AI fills this in automatically.",
        )

        b1, b2 = st.columns(2)
        with b1:
            if st.button("📈 Refresh comps", use_container_width=True,
                         disabled=not (st.session_state.get("query") or "").strip()):
                st.session_state.refresh_comps_pending = True
                st.rerun()
        with b2:
            if st.button("🔁 Re-identify", use_container_width=True,
                         disabled=not (SETTINGS.ai_enabled and _have_img)):
                st.session_state.reidentify_pending = True
                st.rerun()

        # ---- graded-slab verification (PSA cert lookup) ----
        if _PSA_ENABLED:
            with st.expander("🔖 Graded slab? Verify by PSA cert #", expanded=False):
                st.text_input(
                    "PSA certification number",
                    key="cert_input",
                    placeholder="e.g. 108149771",
                    help="Reads the slab's exact card, grade, and PSA population "
                         "straight from PSA, then prices comps for that grade.",
                )
                if st.button(
                    "🔖 Verify slab & price", use_container_width=True,
                    disabled=not (st.session_state.get("cert_input") or "").strip(),
                ):
                    st.session_state.verify_cert_pending = True
                    st.rerun()
                if st.session_state.get("psa_error"):
                    st.warning(st.session_state["psa_error"])

    with right:
        st.subheader("2 · Review, price & copy")
        report = st.session_state.get("report")
        listing: GeneratedListing | None = st.session_state.get("listing")
        identity: CardIdentity | None = st.session_state.get("identity")

        psa_cert = st.session_state.get("psa_cert")

        if listing is None and report is None and not psa_cert:
            st.info(
                "⚡ **Upload a card** — it's identified, priced, and turned into an "
                "eBay listing automatically. You can edit anything here before saving, "
                "and copy each field with one click."
            )
        else:
            if psa_cert:
                render_psa_panel(psa_cert)
            # ---- editable listing fields (values driven by session_state, which
            #      the pipeline sets on each new identification) ----
            st.session_state.setdefault("f_title", (listing.ebay_title if listing else "") or "")
            st.session_state.setdefault("f_desc", (listing.description if listing else "") or "")
            st.session_state.setdefault(
                "f_cond", (listing.suggested_condition if listing else "Raw") or "Raw")

            title = st.text_input("eBay title (≤ 80 chars)", max_chars=80, key="f_title")
            st.caption(f"{len(title)}/80 characters")

            description = st.text_area("Description", height=180, key="f_desc")
            condition = st.text_input("Condition", key="f_cond")

            if identity is not None and isinstance(identity.confidence, (int, float)) \
                    and identity.confidence:
                st.caption(f"AI identification confidence: **{identity.confidence:.0%}**"
                           + (f" — {identity.notes}" if identity.notes else ""))

            # ---- valuation ----
            if report is not None:
                v = report["valuation"]
                st.divider()
                st.markdown(f"**Data sources:** {provenance_badges(report['sources_used'])}")

                if v.get("n"):
                    c1, c2, c3 = st.columns(3)
                    cur = v.get("currency", "USD")
                    c1.metric("Estimated value", f"{cur} {v['estimate']:,.2f}")
                    c2.metric(f"Typical range ({v.get('range_kind', 'range')})",
                              f"{v['low']:,.0f} – {v['high']:,.0f}")
                    c3.metric("Confidence",
                              f"{_CONF_COLOR.get(v['confidence'], '⚪️')} {v['confidence']}")
                    st.caption(
                        f"Based on **{v['n']}** sold comps · median "
                        f"{cur} {v['median']:,.2f} · trimmed mean {cur} "
                        f"{v['trimmed_mean']:,.2f} · min {v['minimum']:,.2f} · "
                        f"max {v['maximum']:,.2f}"
                    )
                else:
                    outage = any(
                        "130point" in w.lower() and ("fail" in w.lower() or "large" in w.lower())
                        for w in report.get("warnings", [])
                    )
                    if outage:
                        st.error(
                            "Couldn't reach 130point right now — sold comps are "
                            "temporarily unavailable. Please try again shortly."
                        )
                    else:
                        st.warning("No sold comps found for this query — try simplifying it.")

                for note in v.get("notes", []):
                    st.caption(f"ℹ️ {note}")
                for w in report.get("warnings", []):
                    st.caption(f"⚠️ {w}")

                # ---- price trend (mirrors the valuation's currency + window) ----
                chart = sold_chart_df(
                    report["sold_comps"],
                    currency=v.get("currency"),
                    recency_days=st.session_state.get("report_recency"),
                )
                if chart is not None:
                    st.markdown("**Sold-price trend**")
                    st.line_chart(chart, height=240)

                # ---- comps tables ----
                if report["sold_comps"]:
                    st.markdown(f"**Recently sold ({len(report['sold_comps'])})**")
                    st.dataframe(
                        comps_table(report["sold_comps"]),
                        use_container_width=True, hide_index=True,
                        column_config={"Link": st.column_config.LinkColumn("Link", display_text="view")},
                    )
                if report["active_comps"]:
                    st.markdown(f"**Active listings ({len(report['active_comps'])})**")
                    st.dataframe(
                        comps_table(report["active_comps"]),
                        use_container_width=True, hide_index=True,
                        column_config={"Link": st.column_config.LinkColumn("Link", display_text="view")},
                    )

            # ---- copy-paste ready (st.code gives a one-click copy button) ----
            st.divider()
            st.markdown("#### 📋 Copy-paste for eBay")
            st.caption("Hover each box and click the copy icon in its top-right corner.")

            st.markdown("**Title**")
            st.code(title or "—", language=None)

            st.markdown("**Description**")
            st.code(description or "—", language=None)

            if report is not None and report["valuation"].get("estimate"):
                v = report["valuation"]
                cur = v.get("currency", "USD")
                pc1, pc2 = st.columns([1, 2])
                with pc1:
                    st.markdown("**Suggested price**")
                    st.code(f"{v['estimate']:,.2f}", language=None)
                with pc2:
                    st.markdown("**Condition**")
                    st.code(condition or "Raw", language=None)
                st.caption(
                    f"Price = median of {v['n']} sold comps · "
                    f"range {cur} {v['low']:,.2f}–{v['high']:,.2f} ({v.get('range_kind', 'range')})"
                )
            else:
                st.markdown("**Condition**")
                st.code(condition or "Raw", language=None)

            # ---- actions ----
            st.divider()
            a1, a2 = st.columns(2)
            with a1:
                if st.button("💾 Save to history", type="primary", use_container_width=True,
                             disabled=report is None):
                    query_str = (st.session_state.get("query") or "").strip()
                    ident = identity
                    if ident is None and psa_cert:
                        ident = CardIdentity(
                            year=psa_cert.get("year", ""),
                            brand=psa_cert.get("brand", ""),
                            player=psa_cert.get("subject", "") or title[:40],
                            card_number=psa_cert.get("card_number", ""),
                            is_graded=True, grader="PSA",
                            grade=str(psa_cert.get("grade", "")),
                            condition=condition or "PSA Graded",
                        )
                    if ident is None:
                        ident = CardIdentity(
                            player=(title[:40] or query_str[:40] or "Unknown")
                        )
                    lst = GeneratedListing(
                        ebay_title=title, description=description,
                        suggested_condition=condition, search_query=query_str,
                    )
                    rep = PriceReport.from_dict(report)
                    img_jpeg = thumb = None
                    if st.session_state.get("pil") is not None:
                        img_jpeg = encode_jpeg(st.session_state.pil)
                        thumb = thumbnail_bytes(st.session_state.pil)
                    try:
                        sid = storage.save_submission(
                            db_path=SETTINGS.db_path, images_dir=SETTINGS.images_dir,
                            identity=ident, listing=lst, report=rep,
                            image_jpeg=img_jpeg, thumb_jpeg=thumb,
                        )
                        st.session_state.saved_id = sid
                        st.success(f"Saved to history (id {sid}). See the History tab.")
                    except (sqlite3.Error, OSError) as exc:
                        st.error(f"Could not save to history: {exc}")
            with a2:
                export_text = (
                    f"TITLE:\n{title}\n\nCONDITION:\n{condition}\n\n"
                    f"DESCRIPTION:\n{description}\n"
                )
                if report and report["valuation"].get("estimate"):
                    v = report["valuation"]
                    export_text += (
                        f"\nSUGGESTED PRICE: {v['currency']} {v['estimate']:,.2f} "
                        f"(range {v['low']:,.2f}–{v['high']:,.2f}, {v['n']} comps)\n"
                    )
                st.download_button(
                    "⬇️ Export listing (.txt)", data=export_text,
                    file_name="listing.txt", mime="text/plain",
                    use_container_width=True,
                )

# =========================================================================== #
# HISTORY
# =========================================================================== #
with tab_history:
    st.subheader("Saved submissions")
    rows = storage.list_submissions(SETTINGS.db_path)
    if not rows:
        st.info("No saved submissions yet. Analyze a card and click **Save to history**.")
    else:
        top = st.columns([3, 1])
        with top[1]:
            st.download_button(
                "⬇️ Export all (CSV)", data=storage.export_csv(SETTINGS.db_path),
                file_name="tcg_history.csv", mime="text/csv", use_container_width=True,
            )

        labels = {
            r["id"]: f"{(r['created_at'] or '')[:16]} · {r['title'] or r['player'] or r['query'] or r['id']}"
            for r in rows
        }
        chosen = st.selectbox(
            "Select a submission", options=list(labels.keys()),
            format_func=lambda i: labels[i],
        )
        rec = storage.get_submission(SETTINGS.db_path, chosen) if chosen else None
        if rec:
            c1, c2 = st.columns([1, 1.5], gap="large")
            with c1:
                if rec.get("image_path"):
                    try:
                        st.image(rec["image_path"], use_container_width=True)
                    except Exception:
                        st.caption("(image unavailable)")
                if st.button("🗑️ Delete this submission", use_container_width=True):
                    storage.delete_submission(SETTINGS.db_path, chosen)
                    st.rerun()
            with c2:
                # st.subheader renders its argument as plain text (no markdown
                # link/image parsing) — safe for model-generated titles.
                st.subheader(rec.get("title") or "(untitled)")
                cur = rec.get("currency") or "USD"
                if rec.get("estimate") is not None:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Estimate", f"{cur} {rec['estimate']:,.2f}")
                    if rec.get("low") is not None and rec.get("high") is not None:
                        m2.metric("Range", f"{rec['low']:,.0f}–{rec['high']:,.0f}")
                    m3.metric("Confidence",
                              f"{_CONF_COLOR.get(rec.get('confidence'), '⚪️')} {rec.get('confidence')}")
                st.caption(
                    f"Saved {rec.get('created_at', '')} · {rec.get('n_comps', 0)} comps · "
                    f"sources: {', '.join(rec.get('sources') or [])}"
                )
                st.markdown("**Condition**")
                st.text(rec.get("condition") or "—")          # plain text, no markdown
                with st.expander("Description", expanded=False):
                    st.text(rec.get("description") or "")
                rep = rec.get("report")
                if rep:
                    chart = sold_chart_df(rep.get("sold_comps", []), currency=cur)
                    if chart is not None:
                        st.line_chart(chart, height=220)
                    if rep.get("sold_comps"):
                        with st.expander(f"Sold comps snapshot ({len(rep['sold_comps'])})"):
                            st.dataframe(comps_table(rep["sold_comps"]),
                                         use_container_width=True, hide_index=True)

# =========================================================================== #
# SETTINGS & ABOUT
# =========================================================================== #
with tab_about:
    st.subheader("What this tool does")
    st.markdown(
        """
This tool turns a **photo of a trading card** into a sell-ready **eBay title +
description** and a **market-based value estimate** built from *real* comparable
sales — then lets you **save every analysis to a local history**.

**Data provenance (so you always know what's real):**
- 🟩 **Sold comps** come live from **130point.com**, which aggregates completed
  eBay sales. This needs **no API key** and is always on.
- 🟩 **AI identification** — two options, both optional:
  - **Ollama** (free, runs locally, no account needed): `ollama pull qwen2.5vl:7b`
  - **Claude** (cloud, best quality): set `ANTHROPIC_API_KEY`
- 🟩 **Active comps** use eBay's **official Browse API** when credentials are set.
- 🟥 Anything labelled **SIMULATED / DEMO** is synthetic and only shown as an
  explicit fallback — never mixed into a real estimate.
        """
    )
    st.subheader("Enable the optional integrations")
    if SETTINGS.anthropic_api_key:
        _claude_status = f"🟢 enabled (model: `{SETTINGS.anthropic_model}`)"
    else:
        _claude_status = "⚪️ off"
    if _OLLAMA_ENABLED:
        _ollama_status = f"🟢 enabled (model: `{_OLLAMA_MODEL}`)"
    else:
        _ollama_status = "⚪️ off"
    st.markdown(
        f"""
| Capability | Status | How to enable |
|---|---|---|
| AI via **Ollama** (free, local) | {_ollama_status} | Install [Ollama](https://ollama.com), run `ollama pull qwen2.5vl:7b`, set `OLLAMA_BASE_URL=http://localhost:11434` |
| AI via **Claude** (cloud) | {_claude_status} | Set `ANTHROPIC_API_KEY` (env or `.streamlit/secrets.toml`) |
| eBay active comps | {'🟢 enabled' if SETTINGS.ebay_enabled else '⚪️ off'} | Set `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` |
| **PSA slab verify** (graded cards) | {'🟢 enabled' if _PSA_ENABLED else '⚪️ off'} | Set `PSA_API_TOKEN` — then enter a cert # in the Analyze tab to verify the card, grade, and PSA population |
| Sold comps (130point) | 🟢 always on | — |

When both Claude and Ollama are configured, Claude is used (higher quality).
Data dir: `{SETTINGS.data_dir}`
        """
    )
    st.subheader("Honest limitations")
    st.markdown(
        """
- 130point is an unofficial, best-effort source; markup changes can break parsing
  and heavy automated use may be rate-limited. Treat estimates as guidance.
- A median of sold comps is **not** an appraisal; condition, grading, and
  centering move real prices a lot. Always sanity-check against the actual comps.
- The tool does not place listings or move money — it drafts and prices only.
        """
    )
