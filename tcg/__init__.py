"""TCG Tool — AI baseball/trading-card identification and live market pricing.

A small, honest, testable core that the Streamlit UI (``app.py``) builds on:

- ``tcg.card_ai``  : Claude vision -> structured card identity + listing copy
- ``tcg.sources``  : live market data (130point sold comps, eBay active comps)
- ``tcg.pricing``  : turn comps into a defensible valuation
- ``tcg.storage``  : persistent submission history (SQLite)
- ``tcg.images``   : safe image loading (HEIC, EXIF, decompression-bomb guard)
- ``tcg.config``   : configuration / feature detection
- ``tcg.models``   : plain dataclasses passed between the layers
"""

__version__ = "1.0.0"
