import streamlit as st

st.set_page_config(
    page_title="Customer Matching",
    page_icon="🔍",
    layout="wide",
)

# Redirect to the new default page for the updated schema
st.switch_page("pages/1_Generate_Samples_and_Assign.py")