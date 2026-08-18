"""SQLAlchemy connection wrapper for hr_oltp and hr_olap."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Database:
    """Manage read/write access to the OLTP and OLAP MySQL databases."""

    TENURE_RANKING_QUERY = """
        SELECT
            ranked.employee_id,
            ranked.employee_name,
            ranked.dept_name,
            ranked.tenure_days,
            ranked.tenure_rank
        FROM (
            SELECT
                de.employee_id,
                de.name AS employee_name,
                dd.dept_name,
                f.tenure_days,
                RANK() OVER (
                    PARTITION BY dd.dept_name
                    ORDER BY f.tenure_days DESC
                ) AS tenure_rank
            FROM hr_olap.fact_employee_performance AS f
            INNER JOIN hr_olap.dim_employee AS de
                ON f.employee_key = de.employee_key
                AND de.is_current = TRUE
            INNER JOIN hr_olap.dim_department AS dd
                ON f.department_key = dd.department_key
            GROUP BY
                de.employee_id,
                de.name,
                dd.dept_name,
                f.tenure_days
        ) AS ranked
        ORDER BY ranked.dept_name, ranked.tenure_rank
    """

    MONTHLY_ATTRITION_QUERY = """
        WITH employee_snapshot AS (
            SELECT DISTINCT
                de.employee_id,
                dd.year,
                dd.month,
                DATE_FORMAT(dd.full_date, '%Y-%m') AS report_month,
                f.is_attrition_flag
            FROM hr_olap.fact_employee_performance AS f
            INNER JOIN hr_olap.dim_employee AS de
                ON f.employee_key = de.employee_key
                AND de.is_current = TRUE
            INNER JOIN hr_olap.dim_date AS dd
                ON f.date_key = dd.date_key
        ),
        monthly_headcount AS (
            SELECT
                ms.year,
                ms.month,
                DATE_FORMAT(ms.month_start, '%Y-%m') AS report_month,
                COUNT(DISTINCT ea.employee_id) AS active_headcount
            FROM (
                SELECT DISTINCT
                    year,
                    month,
                    STR_TO_DATE(CONCAT(year, '-', month, '-01'), '%Y-%m-%d') AS month_start,
                    LAST_DAY(STR_TO_DATE(CONCAT(year, '-', month, '-01'), '%Y-%m-%d')) AS month_end
                FROM hr_olap.dim_date
            ) AS ms
            INNER JOIN hr_oltp.employees AS ea
                ON ea.hire_date <= ms.month_end
            GROUP BY ms.year, ms.month, ms.month_start
        ),
        monthly_attrition AS (
            SELECT
                year,
                month,
                report_month,
                COUNT(*) AS headcount_at_snapshot,
                SUM(CASE WHEN is_attrition_flag = TRUE THEN 1 ELSE 0 END) AS attrition_count
            FROM employee_snapshot
            GROUP BY year, month, report_month
        )
        SELECT
            mh.report_month,
            mh.active_headcount,
            COALESCE(ma.attrition_count, 0) AS attrition_count,
            ROUND(
                100.0 * COALESCE(ma.attrition_count, 0) / NULLIF(mh.active_headcount, 0),
                2
            ) AS monthly_attrition_rate_pct
        FROM monthly_headcount AS mh
        LEFT JOIN monthly_attrition AS ma
            ON mh.year = ma.year
            AND mh.month = ma.month
        WHERE mh.active_headcount > 0
        ORDER BY mh.year, mh.month
    """

    HEADCOUNT_BY_DEPARTMENT_QUERY = """
        SELECT
            dd.dept_name,
            COUNT(DISTINCT de.employee_id) AS headcount
        FROM hr_olap.fact_employee_performance AS f
        INNER JOIN hr_olap.dim_department AS dd
            ON f.department_key = dd.department_key
        INNER JOIN hr_olap.dim_employee AS de
            ON f.employee_key = de.employee_key
            AND de.is_current = TRUE
        GROUP BY dd.dept_name
        ORDER BY dd.dept_name
    """

    EMPLOYEE_SCD2_SALARY_QUERY = """
        SELECT
            eh.effective_start,
            eh.effective_end,
            eh.role,
            eh.salary,
            eh.is_current
        FROM hr_oltp.employee_history AS eh
        WHERE eh.employee_id = :employee_id
        ORDER BY eh.effective_start
    """

    def __init__(
        self,
        oltp_engine: Engine | None = None,
        olap_engine: Engine | None = None,
    ) -> None:
        self.oltp_engine = oltp_engine or self._build_engine("OLTP_DATABASE", "hr_oltp")
        self.olap_engine = olap_engine or self._build_engine("OLAP_DATABASE", "hr_olap")

    @staticmethod
    def _build_engine(env_var: str, default_db: str) -> Engine:
        load_dotenv(PROJECT_ROOT / ".env")
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        user = os.getenv("DB_USER", "root")
        password = os.getenv("DB_PASSWORD", "")
        database = os.getenv(env_var, default_db)
        if not password:
            raise ValueError(
                f"DB_PASSWORD is not set. Create {PROJECT_ROOT / '.env'} "
                "(see .env.example) with your MySQL credentials."
            )
        url = f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}"
        return create_engine(url)

    def read_oltp(self, query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return pd.read_sql(text(query), self.oltp_engine, params=params or {})

    def read_olap(self, query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return pd.read_sql(text(query), self.olap_engine, params=params or {})

    def get_departments(self) -> pd.DataFrame:
        return self.read_oltp(
            "SELECT dept_id, dept_name FROM departments ORDER BY dept_name"
        )

    def get_projects(self) -> pd.DataFrame:
        return self.read_oltp(
            """
            SELECT project_id, project_name, start_date, end_date
            FROM projects
            ORDER BY project_name
            """
        )

    def get_employees_for_select(self) -> pd.DataFrame:
        return self.read_oltp(
            """
            SELECT employee_id, name, current_role
            FROM employees
            ORDER BY name
            """
        )

    def get_monthly_attrition(self) -> pd.DataFrame:
        return self.read_olap(self.MONTHLY_ATTRITION_QUERY)

    def get_headcount_by_department(self) -> pd.DataFrame:
        return self.read_olap(self.HEADCOUNT_BY_DEPARTMENT_QUERY)

    def get_tenure_rankings(self, top_n: int = 5) -> pd.DataFrame:
        df = self.read_olap(self.TENURE_RANKING_QUERY)
        return df[df["tenure_rank"] <= top_n].copy()

    def get_employee_salary_history(self, employee_id: int) -> pd.DataFrame:
        return self.read_oltp(
            self.EMPLOYEE_SCD2_SALARY_QUERY,
            {"employee_id": employee_id},
        )

    def add_employee_with_assignment(
        self,
        name: str,
        email: str,
        dept_id: int,
        hire_date: str,
        current_salary: float,
        current_role: str,
        status: str,
        project_id: int,
        allocation_pct: float,
        assignment_start: str,
    ) -> int:
        with self.oltp_engine.begin() as conn:
            next_id = conn.execute(
                text("SELECT COALESCE(MAX(employee_id), 0) + 1 FROM employees")
            ).scalar_one()

            conn.execute(
                text(
                    """
                    INSERT INTO employees (
                        employee_id, name, email, dept_id, hire_date,
                        current_salary, current_role, status
                    ) VALUES (
                        :employee_id, :name, :email, :dept_id, :hire_date,
                        :current_salary, :current_role, :status
                    )
                    """
                ),
                {
                    "employee_id": next_id,
                    "name": name,
                    "email": email,
                    "dept_id": dept_id,
                    "hire_date": hire_date,
                    "current_salary": current_salary,
                    "current_role": current_role,
                    "status": status,
                },
            )

            conn.execute(
                text(
                    """
                    INSERT INTO employee_history (
                        employee_id, role, salary,
                        effective_start, effective_end, is_current
                    ) VALUES (
                        :employee_id, :role, :salary,
                        :effective_start, NULL, TRUE
                    )
                    """
                ),
                {
                    "employee_id": next_id,
                    "role": current_role,
                    "salary": current_salary,
                    "effective_start": hire_date,
                },
            )

            next_assignment_id = conn.execute(
                text("SELECT COALESCE(MAX(assignment_id), 0) + 1 FROM assignments")
            ).scalar_one()

            conn.execute(
                text(
                    """
                    INSERT INTO assignments (
                        assignment_id, employee_id, project_id,
                        allocation_pct, start_date, end_date
                    ) VALUES (
                        :assignment_id, :employee_id, :project_id,
                        :allocation_pct, :start_date, NULL
                    )
                    """
                ),
                {
                    "assignment_id": next_assignment_id,
                    "employee_id": next_id,
                    "project_id": project_id,
                    "allocation_pct": allocation_pct,
                    "start_date": assignment_start,
                },
            )

        return int(next_id)
