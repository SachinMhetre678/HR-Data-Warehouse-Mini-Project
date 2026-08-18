# Project: HR Data Warehouse Mini Project

## What this is
A dual-database project demonstrating OLTP → ETL → OLAP star schema → BI dashboard.
Two MySQL DBs: `hr_oltp` (operational) and `hr_olap` (analytical, star schema).

## OLTP schema (hr_oltp)
- employees(employee_id, name, email, dept_id, hire_date, current_salary, current_role, status)
- departments(dept_id, dept_name)
- projects(project_id, project_name, start_date, end_date, budget)
- assignments(assignment_id, employee_id, project_id, allocation_pct, start_date, end_date)
- employee_history(history_id, employee_id, role, salary, effective_start, effective_end, is_current) -- SCD Type 2

## OLAP schema (hr_olap) — star schema
- fact_employee_performance(employee_key FK, department_key FK, project_key FK, date_key FK, salary, allocation_pct, tenure_days, is_attrition_flag, job_satisfaction, work_life_balance, overtime, performance_rating, distance_from_home)
- dim_employee(employee_key, employee_id, name, role, is_current, effective_start, effective_end) -- SCD2 lives here
- dim_department(department_key, dept_name)
- dim_project(project_key, project_name, budget)
- dim_date(date_key, full_date, month, quarter, year)

## Folder structure (do not deviate)
hr-data-warehouse/
├── data_synthesizer/generate_data.py
├── etl/{extractor.py, transformer.py, loader.py}
├── run_etl.py
├── database/{oltp_ddl.sql, olap_ddl.sql, stored_procedures.sql, analytical_queries.sql}
├── app/{main.py, db_connector.py, pages/1_Add_Employee.py, pages/2_Dashboard.py}
├── diagrams/
├── README.md
└── requirements.txt

## Data source
Base employee data comes from the Kaggle IBM HR Attrition dataset (`data_synthesizer/raw/WA_Fn-UseC_-HR-Employee-Attrition.csv`, 1,470 rows, single snapshot, no time series). Names/emails, hire_date, SCD2 history, and projects/assignments are synthesized on top of it — see column mapping in the build guide. Do not invent employee attribute values (salary, satisfaction scores, etc.) when real ones exist in the CSV.

## Conventions
- OOP for generators and ETL classes (EmployeeGenerator, ProjectGenerator, AssignmentGenerator, Extractor, Transformer, Loader).
- SCD2 logic: on a role/salary change, close the old dim_employee row (set effective_end, is_current=False) and insert a new row (is_current=True). Never overwrite history.
- Use SQLAlchemy + pandas for DB I/O where possible instead of raw connector calls, for cleaner testability.
- Config (DB host/user/pass) goes in a `.env` file, loaded via python-dotenv. Never hardcode credentials in scripts.
- Keep functions small and testable — this is a QA-minded project, so write things so they could be unit tested even if we don't write full test suites for every piece.
- After generating each phase, tell me what to run and what output to expect, so I can verify before moving to the next phase.