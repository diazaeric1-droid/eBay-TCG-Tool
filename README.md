# 🃏 AI Trading-Card Lister & Pricer

Turn a **photo of a trading card** into a sell-ready **eBay title + description** and a
**market-based value estimate** built from *real* comparable sales — then keep a **local
history** of everything you've analyzed.

> **What changed from the original?** The first version was a UI mock: it never read the
> card, made no network calls, and returned the same hard-coded `$85.00 / "2025 Topps
> Chrome Cosmic Style Card"` for every upload (only the filename changed). This version
> does the real thing — and clearly labels what's real vs. simulated. See
> [`AUDIT.md`](AUDIT.md) for the full before/after.

---

## What it actually does

| Capability | How it works | Needs a key? |
|---|---|---|
| 🟩 **Sold comps & price estimate** | Live from **[130point.com](https://130point.com)**, which aggregates completed eBay sales | **No** — always on |
| 🟩 **AI card identification + listing copy** | **Claude** vision (Opus 4.8) reads the card and drafts the title/description | Optional (`ANTHROPIC_API_KEY`) |
| 🟩 **Active "similar listings" comps** | eBay's official **Browse API** | Optional (eBay app creds) |
| 🟩 **Submission history** | Every analysis is saved to a local SQLite DB with its image, comps, and valuation | **No** |

Without any keys, the app is still useful: **type the card in → get real sold comps and a
real estimate.** Add an Anthropic key to make it fully automatic from a photo.

The estimate is **outlier-robust**: the headline number is the **median** of sold comps,
the range is the **interquartile range (p25–p75)**, and a **confidence** rating reflects
sample size and price spread. Anything synthetic is tagged `🟥 SIMULATED` and never mixed
into a real estimate.

---

## Quick start

```bash
git clone https://github.com/diazaeric1-droid/eBay-TCG-Tool.git
cd eBay-TCG-Tool
python -m venv .venv && source .venv/bin/activate     # optional but recommended
pip install -r requirements.txt
streamlit run app.py
```

Then open the URL Streamlit prints (usually <http://localhost:8501>).

### Enable AI identification (optional)

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # or put it in .streamlit/secrets.toml
```

### Enable eBay active comps (optional)

Create an app at <https://developer.ebay.com/> and set:

```bash
export EBAY_CLIENT_ID=...
export EBAY_CLIENT_SECRET=...
```

All settings can also live in `.streamlit/secrets.toml` (see
`.streamlit/secrets.toml.example`) or a `.env` (see `.env.example`).

---

## Using it

1. **Analyze** tab → upload a card photo (JPG/PNG/WebP/HEIC).
2. Click **🤖 Identify with AI** (if enabled) — or type the card in the **search query** box.
3. Pick a **comp window** (e.g. last 90 days) and click **📈 Get / refresh comps**.
4. Review the estimate, range, confidence, sold-price trend, and the actual comps.
   Edit the title/description as needed.
5. **💾 Save to history** or **⬇️ Export listing**.
6. **History** tab → revisit or delete past submissions; export all as CSV.

---

## Architecture

UI is presentation-only; all logic lives in the `tcg/` package (no Streamlit imports there,
so it's fully unit-testable).

```
app.py            Streamlit UI: Analyze / History / Settings tabs
tcg/
  models.py       Typed, JSON-serializable dataclasses (the data contract)
  config.py       Settings from env / st.secrets; feature detection
  images.py       Safe image loading: HEIC, EXIF, decompression-bomb guard
  card_ai.py      Claude vision -> CardIdentity + GeneratedListing (forced tool-use)
  sources.py      Live data: OnePointSource (130point), EbaySource (Browse API), DemoSource
  pricing.py      Comps -> Valuation (median / IQR / confidence) + PricingEngine
  storage.py      SQLite submission history (save / list / get / delete / export)
tests/            pytest suite (parser, pricing, storage, images, AI-with-mock)
```

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest                 # 22 tests: parser (real fixture), pricing math, storage, images, AI
pip-audit              # scan dependencies for known CVEs
```

The 130point parser is tested against a captured real response
(`tests/fixtures/onepoint_sample.html`) so it runs offline.

---

## Honest limitations

- **130point is an unofficial, best-effort source.** A markup change can break parsing, and
  heavy automated use may get rate-limited. Treat estimates as guidance, not gospel.
- **A median of sold comps is not an appraisal.** Condition, grade, and centering move real
  prices a lot — always sanity-check against the actual comps shown.
- **The tool does not place listings or move money.** It drafts and prices only.
- **Scraping caveat:** active comps deliberately use eBay's *official Browse API* rather than
  scraping eBay's HTML search pages (which violates their ToS and breaks constantly).

---

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables AI identification |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Vision model |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | — | Enables eBay active comps |
| `EBAY_ENV` | `production` | `production` or `sandbox` |
| `EBAY_MARKETPLACE` | `EBAY_US` | eBay marketplace id |
| `TCG_DATA_DIR` | `data` | Where history DB + images live |
| `TCG_MAX_UPLOAD_MB` | `25` | Reject uploads larger than this |
| `TCG_MAX_IMAGE_PIXELS` | `60000000` | Decompression-bomb ceiling |
| `TCG_COMP_LIMIT` | `40` | Max comps fetched per source |
