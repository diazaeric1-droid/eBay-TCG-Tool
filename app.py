# app.py
# Paste your Python code below.

import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image
import pillow_heif
from datetime import datetime, timedelta

# Register the HEIF opener with PIL so it can read .heic files
pillow_heif.register_heif_opener()

# --- MOCKED BACKEND LOGIC ---
def mock_process_card(image_file):
    """Simulates the Vision API and pricing engine with a 3-month timeframe."""
    today = datetime.now()
    dates = [(today - timedelta(days=90 - i*8)).strftime("%b %d") for i in range(12)]
    sold_prices = [65, 70, 75, 68, 80, 85, 90, 85, 100, 110, 105, 115]
    
    sold_listings = []
    for i in reversed(range(len(dates))):
        sold_listings.append({
            "Date": dates[i],
            "Listing Title": "2025 Topps Chrome Cosmic James Wood Stella Nova Gold /50",
            "Condition": "Raw",
            "Sold Price": f"${sold_prices[i]:.2f}"
        })

    return {
        "Title": "2025 Topps Chrome Cosmic James Wood Stella Nova Gold Die-Cut RC /50",
        "Description": "ITEM DETAILS\nCard: 2025 Topps Chrome Cosmic James Wood\nCard Number: #SN-10\nAttributes: Stella Nova Insert, Gold Parallel, Die-Cut, Rookie Card\nCondition: Raw\n\nSHIPPING DETAILS\nCard will be shipped securely in a penny sleeve, top loader, bubble wrapped, and mailed in a sturdy box.",
        "Estimated_Value": "$85.00",
        "Range": "$65.00 - $115.00",
        "chart_dates": dates,
        "chart_prices": sold_prices,
        "active_listings": [
            {"Listing Title": "2025 Topps Chrome Cosmic James Wood Stella Nova Gold /50", "Condition": "Raw", "Price": "$75.00"},
            {"Listing Title": "James Wood 2025 Topps Chrome Cosmic Stella Nova GOLD /50 RC", "Condition": "Raw", "Price": "$89.99"},
            {"Listing Title": "2025 Cosmic Chrome James Wood Stella Nova Gold Die Cut /50", "Condition": "Raw", "Price": "$110.00"}
        ],
        "sold_listings": sold_listings
    }

# --- STREAMLIT UI ---
st.set_page_config(page_title="AI Baseball Card Lister", layout="wide")
st.title("⚾ AI Baseball Card Lister & Pricer")

# --- STATE RESET MECHANISM ---
# Track the file name in session state. If it changes, wipe the previous results.
if 'current_file_name' not in st.session_state:
    st.session_state.current_file_name = None

col1, col2 = st.columns([1, 1.2])

with col1:
    st.subheader("1. Upload Card")
    uploaded_file = st.file_uploader("Choose a card image...", type=["jpg", "jpeg", "png", "heic", "heif"])
    
    if uploaded_file is not None:
        # Check if the user just uploaded a brand new file
        if st.session_state.current_file_name != uploaded_file.name:
            st.session_state.current_file_name = uploaded_file.name
            if 'result' in st.session_state:
                del st.session_state.result  # Wipe old card data instantly
                st.rerun() # Refresh the page state smoothly
        
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Card", use_container_width=True)
        
        if st.button("Process Card", type="primary", use_container_width=True):
            with st.spinner('Analyzing card and fetching 3-month comps...'):
                st.session_state.result = mock_process_card(uploaded_file)
                st.rerun()
                
    else:
        # If the file uploader is cleared out entirely by the user, clear the data
        if st.session_state.current_file_name is not None:
            st.session_state.current_file_name = None
            if 'result' in st.session_state:
                del st.session_state.result
                st.rerun()

with col2:
    st.subheader("2. Generated Listing")
    
    if 'result' in st.session_state:
        res = st.session_state.result
        
        st.text_input("eBay Title", value=res["Title"], max_chars=80)
        st.text_area("Description (Copy/Paste Ready)", value=res["Description"], height=170)
        st.text_input("Estimated True Value", value=f"{res['Estimated_Value']} (Range: {res['Range']})")
        
        st.divider()
        st.subheader("3. Market Data (Last 90 Days)")
        
        # ACTIVE LISTINGS TABLE
        st.markdown("**Active Listings (Similar Cards)**")
        df_active = pd.DataFrame(res["active_listings"])
        st.dataframe(df_active, use_container_width=True, hide_index=True)
        
        # 3-MONTH CHART
        st.markdown("**Sold Price Trend (3 Months)**")
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(res["chart_dates"], res["chart_prices"], marker='o', color='#2E86C1', linewidth=2)
        ax.set_ylabel("Sale Price ($)")
        ax.grid(True, linestyle='--', alpha=0.5)
        plt.xticks(rotation=45, ha='right')
        st.pyplot(fig)
        
        # SOLD LISTINGS TABLE
        st.markdown("**Recently Sold**")
        df_sold = pd.DataFrame(res["sold_listings"])
        st.dataframe(df_sold, use_container_width=True, hide_index=True)
        
    else:
        st.info("Ready for your next card! Upload an image and click 'Process Card' to begin.")