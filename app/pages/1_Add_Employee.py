"""Add a new employee and project assignment to hr_oltp."""

import sys
from datetime import date
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db_connector import Database

st.set_page_config(page_title="Add Employee", layout="wide")
st.title("Add Employee")
st.caption("Writes a new employee, SCD2 history row, and project assignment to hr_oltp.")

try:
    db = Database()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

departments = db.get_departments()
projects = db.get_projects()

if departments.empty or projects.empty:
    st.warning("Load OLTP data first (`python data_synthesizer/generate_data.py`).")
    st.stop()

with st.form("add_employee_form"):
    st.subheader("Employee details")
    col1, col2 = st.columns(2)

    with col1:
        name = st.text_input("Full name", placeholder="Jane Smith")
        email = st.text_input("Email", placeholder="jane.smith@company.com")
        dept_name = st.selectbox(
            "Department",
            departments["dept_name"].tolist(),
        )
        hire_date = st.date_input("Hire date", value=date.today())

    with col2:
        current_role = st.text_input("Role", placeholder="Research Scientist")
        current_salary = st.number_input(
            "Monthly salary",
            min_value=0.0,
            value=5000.0,
            step=100.0,
        )
        status = st.selectbox("Status", ["Active", "Terminated"])

    st.subheader("Project assignment")
    col3, col4 = st.columns(2)

    with col3:
        project_name = st.selectbox(
            "Project",
            projects["project_name"].tolist(),
        )
        allocation_pct = st.number_input(
            "Allocation %",
            min_value=1.0,
            max_value=100.0,
            value=50.0,
            step=5.0,
        )

    with col4:
        assignment_start = st.date_input(
            "Assignment start date",
            value=hire_date,
        )

    submitted = st.form_submit_button("Save employee", type="primary")

if submitted:
    if not name or not email or not current_role:
        st.error("Name, email, and role are required.")
    elif assignment_start < hire_date:
        st.error("Assignment start date cannot be before hire date.")
    else:
        dept_id = int(
            departments.loc[departments["dept_name"] == dept_name, "dept_id"].iloc[0]
        )
        project_id = int(
            projects.loc[projects["project_name"] == project_name, "project_id"].iloc[0]
        )

        try:
            employee_id = db.add_employee_with_assignment(
                name=name.strip(),
                email=email.strip(),
                dept_id=dept_id,
                hire_date=hire_date.isoformat(),
                current_salary=float(current_salary),
                current_role=current_role.strip(),
                status=status,
                project_id=project_id,
                allocation_pct=float(allocation_pct),
                assignment_start=assignment_start.isoformat(),
            )
            st.success(
                f"Employee **{name}** saved with ID `{employee_id}`. "
                "Run `python run_etl.py` to load into hr_olap."
            )
        except Exception as exc:
            st.error(f"Failed to save employee: {exc}")
