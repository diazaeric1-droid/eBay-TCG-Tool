import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image
import pillow_heif
from datetime import datetime, timedelta

# Register the HEIF opener with PIL so it can read .heic files
pillow_heif.register_heif_opener()

# --- DYNAMIC BACKEND LOGIC ---
def process_card_data(image_file):
    """
    Simulates the Vision API and pricing engine.
    Uses the uploaded filename to prove the application state is updating dynamically.
    """
    today = datetime.now()
    # Generate 90 days of timeline data (12 points)
    dates = [(today - timedelta(days=90 - i*8)).strftime("%b %d") for i in range(12)]
    sold_prices = [65, 70, 75, 68, 80, 85, 90, 85, 100, 110, 105, 115]
    
    # Generate sold listings table based on the filename
    sold_listings = []
    for i in reversed(range(len(dates))):
        sold_listings.append({
            "Date": dates[i],
            "Listing Title": f"Recent Sale matching {image_file.name}",
            "Condition": "Raw",
            "Sold Price": f"${sold_prices[i]:.2f}"
        })

    # Cleaned line titles (no markdown **) for a professional look
    description_text = (
        f"ITEM DETAILS\n"
        f"Card File processed: {image_file.name}\n"
        f"Card Number: #SN-10\n"
        f"Attributes: Premium Parallel, Die-Cut, Rookie Card\n"
        f"Condition: Raw\n\n"
        f"SHIPPING DETAILS\n"
        f"Card will be shipped securely in a penny sleeve, top loader, bubble wrapped, and mailed in a sturdy box."
    )

    return {
        "Title": f"2025 Topps Chrome Cosmic Style Card - {image_file.name[:30]}",
        "Description": description_text,
        "Estimated_Value": "$85.00",
        "Range": "$65.00 - $115.00",
        "chart_dates": dates,
        "chart_prices": sold_prices,
        "active_listings": [
            {"Listing Title": f"Active Comp 1 for {image_file.name[:25]}...", "Condition": "Raw", "Price": "$75.00"},
            {"Listing Title": f"Active Comp 2 for {image_file.name[:25]}...", "Condition": "Raw", "Price": "$89.99"},
            {"Listing Title": f"Active Comp 3 for {image_file.name[:25]}...", "Condition": "Raw", "Price": "$110.00"}
        ],
        "sold_listings": sold_listings
    }

# --- STREAMLIT UI CONFIGURATION ---
st.set_page_config(page_title="AI Baseball Card Lister", layout="wide")
st.title("⚾ AI Baseball Card Lister & Pricer")

# --- STATE RESET MECHANISM ---
if 'current_file_name' not in st.session_state:
    st.session_state.current_file_name = None

col1, col2 = st.columns([1, 1.2])

with col1:
    st.subheader("1. Upload Card")
    uploaded_file = st.file_uploader("Choose a card image...", type=["jpg", "jpeg", "png", "heic", "heif"])
    
    if uploaded_file is not None:
        # If a completely different file is uploaded, wipe out the old memory instantly
        if st.session_state.current_file_name != uploaded_file.name:
            st.session_state.current_file_name = uploaded_file.name
            if 'result' in st.session_state:
                del st.session_state.result
            st.rerun()
        
        # Display the uploaded image
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Card", use_container_width=True)
        
        if st.button("Process Card", type="primary", use_container_width=True):
            with st.spinner('Analyzing card and fetching 3-month comps...'):
                st.session_state.result = process_card_data(uploaded_file)
                st.rerun()
                
    else:
        # Reset everything if the user clears out the file uploader completely
        if st.session_state.current_file_name is not None:
            st.session_state.current_file_name = None
            if 'result' in st.session_state:
                del st.session_state.result
            st.rerun()

with col2:
    st.subheader("2. Generated Listing")
    
    if 'result' in st.session_state:
        res = st.session_state.result
        
        # Output Form Fields
        st.text_input("eBay Title", value=res["Title"], max_chars=80)
        st.text_area("Description (Copy/Paste Ready)", value=res["Description"], height=170)
        st.text_input("Estimated True Value", value=f"{res['Estimated_Value']} (Range: {res['Range']})")
        
        st.divider()
        st.subheader("3. Market Data (Last 90 Days)")
        
        # Active Listings Table
        st.markdown("**Active Listings (Similar Cards)**")
        df_active = pd.DataFrame(res["active_listings"])
        st.dataframe(df_active, use_container_width=True, hide_index=True)
        
        # 3-Month Price Graph
        st.markdown("**Sold Price Trend (3 Months)**")
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(res["chart_dates"], res["chart_prices"], marker='o', color='#2E86C1', linewidth=2)
        ax.set_ylabel("Sale Price ($)")
        ax.grid(True, linestyle='--', alpha=0.5)
        plt.xticks(rotation=45, ha='right')
        st.pyplot(fig)
        
        # Recently Sold Table
        st.markdown("**Recently Sold**")
        df_sold = pd.DataFrame(res["sold_listings"])
        st.dataframe(df_sold, use_container_width=True, hide_index=True)
        
    else:
        st.info("Ready for your next card! Upload an image and click 'Process Card' to begin.")