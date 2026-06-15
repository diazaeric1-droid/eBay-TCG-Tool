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
if 'current_file_name' not in st.session