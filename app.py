# app.py
# Paste your Python code below.

import streamlit as st
import matplotlib.pyplot as plt

# --- MOCKED BACKEND LOGIC ---
def mock_process_card(image_file):
    """Simulates the Vision API and pricing engine."""
    return {
        "Title": "2011 Bowman Chrome Draft Mike Trout RC Refractor PSA 9",
        "Description": "**Item:** 2011 Bowman Chrome Draft Mike Trout\n**Card Number:** 101\n**Attributes:** Refractor, Rookie Card\n**Condition/Grade:** PSA 9\n\nCard will be shipped securely in a graded slab sleeve, bubble wrapped, and mailed in a sturdy box.",
        "Estimated_Value": "$1,175.00",
        "Range": "$1,050.00 - $1,250.00",
        "historical_dates": ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Day 7", "Day 8", "Day 9", "Day 10"],
        "historical_prices": [1050, 1075, 1100, 1090, 1150, 1200, 1180, 1220, 1250, 1175]
    }

# --- STREAMLIT UI ---
st.set_page_config(page_title="AI Baseball Card Lister", layout="wide")
st.title("⚾ AI Baseball Card Lister & Pricer")

# Layout: Two columns
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Card")
    uploaded_file = st.file_uploader("Choose a card image...", type=["jpg", "jpeg", "png"])
    
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Uploaded Card", use_column_width=True)
        
        if st.button("Process Card", type="primary"):
            with st.spinner('Analyzing card and fetching comps...'):
                # Call backend
                st.session_state.result = mock_process_card(uploaded_file)

with col2:
    st.subheader("2. Generated Listing & Comps")
    
    # Check if data exists in the session state
    if 'result' in st.session_state:
        res = st.session_state.result
        
        # Editable fields
        st.text_input("eBay Title", value=res["Title"], max_chars=80)
        st.text_area("Description", value=res["Description"], height=150)
        st.text_input("Estimated Cost", value=f"{res['Estimated_Value']} (Range: {res['Range']})")
        
        # Matplotlib Chart
        st.markdown("### Recent Sales Velocity")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(res["historical_dates"], res["historical_prices"], marker='o', color='b')
        ax.set_ylabel("Sale Price ($)")
        ax.grid(True, linestyle='--', alpha=0.6)
        plt.xticks(rotation=45)
        st.pyplot(fig)
    else:
        st.info("Upload an image and click 'Process Card' to see results.")