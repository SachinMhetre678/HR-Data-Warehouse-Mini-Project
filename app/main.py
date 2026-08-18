"""Streamlit entrypoint for the HR Data Warehouse dashboard."""

import streamlit as st

st.set_page_config(
    page_title="HR Data Warehouse",
    page_icon="📊",
    layout="wide",
)

st.title("HR Data Warehouse")
st.markdown(
    """
Welcome to the HR Data Warehouse mini project.

Use the sidebar to navigate:

- **Add Employee** — insert a new employee and project assignment into `hr_oltp`
- **Dashboard** — explore analytics from `hr_olap` (attrition, headcount, salary trends, tenure)

After adding employees in OLTP, run `python run_etl.py` to refresh the warehouse.
"""
)

col1, col2, col3 = st.columns(3)
col1.metric("OLTP database", "hr_oltp")
col2.metric("OLAP database", "hr_olap")
col3.metric("Pipeline", "Extract → Transform → Load")
