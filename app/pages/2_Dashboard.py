"""HR analytics dashboard powered by hr_olap."""

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db_connector import Database

st.set_page_config(page_title="Dashboard", layout="wide")
st.title("HR Analytics Dashboard")
st.caption("Charts sourced from hr_olap and SCD2 salary history in hr_oltp.")

try:
    db = Database()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

top_n = st.sidebar.slider("Top employees by tenure (per department)", 3, 10, 5)

try:
    attrition_df = db.get_monthly_attrition()
    headcount_df = db.get_headcount_by_department()
    tenure_df = db.get_tenure_rankings(top_n=top_n)
    employees_df = db.get_employees_for_select()
except Exception as exc:
    st.error(f"Could not load dashboard data. Run ETL first. Details: {exc}")
    st.stop()

if attrition_df.empty and headcount_df.empty:
    st.warning("No OLAP data found. Run `python run_etl.py` after loading OLTP data.")
    st.stop()

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Monthly attrition rate")
    if attrition_df.empty:
        st.info("No attrition data available.")
    else:
        fig_attrition = px.line(
            attrition_df,
            x="report_month",
            y="monthly_attrition_rate_pct",
            markers=True,
            labels={
                "report_month": "Month",
                "monthly_attrition_rate_pct": "Attrition rate (%)",
            },
        )
        fig_attrition.update_layout(margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_attrition, use_container_width=True)

with chart_col2:
    st.subheader("Headcount by department")
    if headcount_df.empty:
        st.info("No headcount data available.")
    else:
        fig_headcount = px.bar(
            headcount_df,
            x="dept_name",
            y="headcount",
            text="headcount",
            labels={"dept_name": "Department", "headcount": "Employees"},
        )
        fig_headcount.update_traces(textposition="outside")
        fig_headcount.update_layout(margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_headcount, use_container_width=True)

st.subheader("Salary trend (SCD2 history)")
if employees_df.empty:
    st.info("No employees available.")
else:
    employee_labels = {
        f"{row.name} ({row.current_role})": int(row.employee_id)
        for row in employees_df.itertuples(index=False)
    }
    selected_label = st.selectbox("Select employee", list(employee_labels.keys()))
    selected_id = employee_labels[selected_label]

    salary_history = db.get_employee_salary_history(selected_id)
    if salary_history.empty:
        st.info("No SCD2 salary history found for this employee.")
    else:
        salary_history = salary_history.copy()
        salary_history["period_label"] = salary_history.apply(
            lambda row: (
                f"{row['effective_start']} → "
                f"{row['effective_end'] if row['effective_end'] else 'present'}"
            ),
            axis=1,
        )
        fig_salary = px.line(
            salary_history,
            x="effective_start",
            y="salary",
            markers=True,
            hover_data=["role", "is_current"],
            labels={
                "effective_start": "Effective start",
                "salary": "Monthly salary",
            },
            title=f"Salary history for {selected_label}",
        )
        fig_salary.update_layout(margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_salary, use_container_width=True)
        st.dataframe(
            salary_history[
                [
                    "effective_start",
                    "effective_end",
                    "role",
                    "salary",
                    "is_current",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

st.subheader(f"Top {top_n} employees by tenure (window function)")
if tenure_df.empty:
    st.info("No tenure ranking data available.")
else:
    st.dataframe(tenure_df, use_container_width=True, hide_index=True)
