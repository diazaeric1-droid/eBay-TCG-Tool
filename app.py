# app.py
# Paste your Python code below.

import streamlit as st
import matplotlib.pyplot as plt
from PIL import Image
import pillow_heif

# Register the HEIF opener with PIL so it can read .heic files
pillow_heif.register_heif_opener()

# --- MOCKED BACKEND LOGIC ---
def mock_process_card(image_file):
    """Simulates the Vision API and pricing engine."""
    return {
        "Title": "2025 Topps Chrome Cosmic James Wood Stella Nova Gold Die-Cut RC /50",
        "Description": "**Item:** 2025 Topps Chrome Cosmic James Wood\n**Card Number:** #SN-10\n**Attributes:** Stella Nova Insert, Gold Parallel, Die-Cut, Rookie Card\n**Condition/Grade:** Raw\n\nCard will be shipped securely in a penny sleeve, top loader, bubble wrapped, and mailed in a sturdy box.",
        "Estimated_Value": "$85.00",
        "Range": "$65.00 - $115.00",
        "historical_dates": ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Day 10"],
        "historical_prices": [65, 70, 75, 80, 85, 95, 90, 105, 115, 85]
    }

# --- STREAMLIT UI ---
st.set_page_config(page_title="AI Baseball Card Lister", layout="wide")
st.title("⚾ AI Baseball Card Lister & Pricer")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Card")
    # Added 'heic' and 'heif' to the allowed types
    uploaded_file = st.file_uploader("Choose a card image...", type=["jpg", "jpeg", "png", "heic", "heif"])
    
    if uploaded_file is not None:
        # Read the file into a PIL Image object (this auto-converts HEIC)
        image = Image.open(uploaded_file)
        
        # Display the image
        st.image(image, caption="Uploaded Card", use_container_width=True)
        
        if st.button("Process Card", type="primary"):
            with st.spinner('Analyzing card and fetching comps...'):
                st.session_state.result = mock_process_card(uploaded_file)

with col2:
    st.subheader("2. Generated Listing & Comps")
    
    if 'result' in st.session_state:
        res = st.session_state.result
        
        st.text_input("eBay Title", value=res["Title"], max_chars=80)
        st.text_area("Description", value=res["Description"], height=150)
        st.text_input("Estimated Cost", value=f"{res['Estimated_Value']} (Range: {res['Range']})")
        
        st.markdown("### Recent Sales Velocity")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(res["historical_dates"], res["historical_prices"], marker='o', color='b')
        ax.set_ylabel("Sale Price ($)")
        ax.grid(True, linestyle='--', alpha=0.6)
        plt.xticks(rotation=45)
        st.pyplot(fig)
    else:
        st.info("Upload an image and click 'Process Card' to see results.")