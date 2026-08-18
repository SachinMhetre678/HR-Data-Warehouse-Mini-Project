"""Extract operational data from hr_oltp and attrition attributes from the Kaggle CSV."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = (
    PROJECT_ROOT / "data_synthesizer" / "raw" / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
)


def build_oltp_engine() -> Engine:
    load_dotenv(PROJECT_ROOT / ".env")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("OLTP_DATABASE", "hr_oltp")
    if not password:
        raise ValueError(
            f"DB_PASSWORD is not set. Create {PROJECT_ROOT / '.env'} "
            "(see .env.example) with your MySQL credentials."
        )
    url = f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url)


class Extractor:
    """Read OLTP tables and CSV snapshot attributes for the ETL pipeline."""

    ATTRITION_COLUMNS = [
        "EmployeeNumber",
        "Attrition",
        "JobSatisfaction",
        "WorkLifeBalance",
        "OverTime",
        "PerformanceRating",
        "DistanceFromHome",
    ]

    def __init__(
        self,
        engine: Engine | None = None,
        csv_path: Path = CSV_PATH,
    ) -> None:
        self.engine = engine or build_oltp_engine()
        self.csv_path = csv_path

    def extract_departments(self) -> pd.DataFrame:
        return pd.read_sql("SELECT dept_id, dept_name FROM departments", self.engine)

    def extract_employees(self) -> pd.DataFrame:
        query = """
            SELECT
                e.employee_id,
                e.name,
                e.email,
                e.dept_id,
                e.hire_date,
                e.current_salary,
                e.current_role,
                e.status,
                d.dept_name
            FROM employees e
            INNER JOIN departments d ON e.dept_id = d.dept_id
        """
        return pd.read_sql(query, self.engine)

    def extract_projects(self) -> pd.DataFrame:
        return pd.read_sql(
            """
            SELECT project_id, project_name, start_date, end_date, budget
            FROM projects
            """,
            self.engine,
        )

    def extract_assignments(self) -> pd.DataFrame:
        return pd.read_sql(
            """
            SELECT
                assignment_id,
                employee_id,
                project_id,
                allocation_pct,
                start_date,
                end_date
            FROM assignments
            """,
            self.engine,
        )

    def extract_employee_history(self) -> pd.DataFrame:
        return pd.read_sql(
            """
            SELECT
                history_id,
                employee_id,
                role,
                salary,
                effective_start,
                effective_end,
                is_current
            FROM employee_history
            """,
            self.engine,
        )

    def extract_attrition_attributes(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path, usecols=self.ATTRITION_COLUMNS)
        df = df.rename(columns={"EmployeeNumber": "employee_id"})
        df["employee_id"] = df["employee_id"].astype(int)
        df = df.drop_duplicates(subset=["employee_id"])
        return df

    def extract_all(self) -> dict[str, pd.DataFrame]:
        return {
            "departments": self.extract_departments(),
            "employees": self.extract_employees(),
            "projects": self.extract_projects(),
            "assignments": self.extract_assignments(),
            "employee_history": self.extract_employee_history(),
            "attrition_attributes": self.extract_attrition_attributes(),
        }
