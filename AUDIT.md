# Audit & Rebuild Report

A senior-level audit of the original `eBay-TCG-Tool`, and what the rebuild changed.

## The one thing to know

**The original app was a convincing UI mock, not a working pricer.** `app.py`'s
`process_card_data()` docstring said it plainly: *"Simulates the Vision API and pricing
engine."* For **every** uploaded card it returned the identical output —
`Estimated_Value = "$85.00"`, title `"2025 Topps Chrome Cosmic Style Card - <filename>"`,
and a constant sold-price array `[65, 70, 75, 68, 80, 85, 90, 85, 100, 110, 105, 115]`. The
card image was opened only to display it; its pixels were never read. There were **no
network calls** — no 130point, no eBay, no AI. The only things that changed between runs
were the **filename** (spliced into the title/description) and the **system clock** (chart
x-axis).

A reseller pricing inventory on those numbers would be pricing on fiction.

## Findings (original app)

| # | Severity | Area | Finding |
|---|---|---|---|
| 1 | 🔴 Critical | Honesty | All data simulated — no vision, no pricing, no network; identical output per card. |
| 2 | 🔴 Critical | UX | Fabricated numbers shown as authoritative ("Estimated **True** Value"), with a spinner claiming "fetching 3-month comps" while doing zero I/O. No provenance labeling. |
| 3 | 🟠 High | Security | `Image.open(uploaded_file)` with no decompression-bomb guard, no size cap, no EXIF transpose, no error handling → a crafted HEIC/PNG could OOM the shared server; corrupt files throw raw tracebacks; phone photos render sideways. |
| 4 | 🟠 High | Runtime | `matplotlib` figure leak: `plt.subplots()` every rerun, never `plt.close()`. Streamlit reruns on every keystroke → unbounded figure/memory growth. Compounded by a redundant `st.rerun()`. |
| 5 | 🟠 High | Packaging | `requirements.txt` omitted `pandas` (imported by `app.py`) → a clean install **crashes on launch**. Deps unpinned (Pillow/libheif process untrusted bytes). |
| 6 | 🟠 High | UX | Condition hard-wired to "Raw"; no grade input; single point estimate with no sample size, date span, or confidence — wrong for any graded/non-mint card. |
| 7 | 🟡 Medium | UX | No persistence/history and no export; processing the next card silently wiped the previous one. Field edits were never read back. |
| 8 | 🟡 Medium | Security | Raw filename injected unsanitized into "copy/paste-ready" listing text → stored-content-injection surface for downstream HTML. |
| 9 | 🟡 Medium | Quality | Zero tests despite a `tests/` tree; the financial logic (pricing) and parsing were exactly what most needed coverage. |
| 10 | ⚪ Low | Docs | One-line README; no `.gitignore`, no secrets template. |

*(Findings produced by a 5-dimension parallel audit — functional-honesty, runtime, security,
UX, architecture — then consolidated and cross-checked against the source.)*

## What the rebuild changed

| Original | Now |
|---|---|
| Hard-coded `$85.00` for every card | **Real estimate** from live 130point sold comps (median + p25–p75 IQR + confidence) |
| Fake `[65, 70, …]` sold array | **Live sold comps** parsed from 130point (`tcg/sources.py`, tested against a captured fixture) |
| Three invented "active comps" | **eBay Browse API** active comps (official, opt-in) — or an explicit `🟥 SIMULATED` fallback |
| No vision; filename → title | **Claude vision** (`tcg/card_ai.py`) reads the card → structured identity + ≤80-char title + description |
| Numbers shown as "True Value", no provenance | **Provenance badges** (🟩 real / 🟥 simulated), "based on N comps", confidence rating, truthful spinners |
| `Image.open` with no guards | **Hardened loader** (`tcg/images.py`): bomb guard, EXIF transpose, corrupt-file handling, size cap |
| matplotlib leak + double rerun | **`st.line_chart`** — no figure lifecycle; rerun loops removed |
| No history | **SQLite history** (`tcg/storage.py`) + a History tab: revisit, delete, CSV export |
| Filename injected into listing text | Filename never echoed into listing copy |
| `requirements.txt` missing `pandas` | Complete, **pinned** requirements + `requirements-dev.txt` + `pip-audit` |
| Zero tests | **22 passing tests** (parser, pricing math, storage, image safety, AI with a mocked client) |
| 1-line README, no `.gitignore` | Full README, `.gitignore`, `.env.example`, secrets template, this audit |
| 131-line monolith | Presentation-only `app.py` over a testable, Streamlit-free `tcg/` core |

## Verification performed

- `pytest` — 22/22 pass (130point parser runs against a real captured response, offline).
- Live 130point fetch confirmed (e.g. *2018 Topps Chrome Ohtani RC* → 40 comps, median ≈ $336).
- App boots under Streamlit (HTTP 200, health `ok`) and runs clean under Streamlit's
  `AppTest` harness with no exceptions.
- End-to-end: live comps → valuation → save → history readback, all consistent.
