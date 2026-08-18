"""Hybrid data ingestion + synthesis for hr_oltp from the IBM HR Attrition CSV."""

from __future__ import annotations

import os
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from faker import Faker
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

AS_OF_DATE = date(2024, 1, 1)
CSV_PATH = Path(__file__).resolve().parent / "raw" / "WA_Fn-UseC_-HR-Employee-Attrition.csv"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEPT_ROLE_LADDERS: dict[str, list[str]] = {
    "Sales": ["Sales Representative", "Sales Executive", "Manager"],
    "Research & Development": [
        "Laboratory Technician",
        "Research Scientist",
        "Research Director",
        "Manager",
    ],
    "Human Resources": ["Human Resources", "Manager"],
}

ROLE_ALIASES: dict[str, str] = {
    "Healthcare Representative": "Sales Representative",
    "Manufacturing Director": "Research Director",
}


def _subtract_years_months(base: date, years: int, months: int) -> date:
    """Return a calendar date offset backward from base by years and months."""
    ts = pd.Timestamp(base) - pd.DateOffset(years=years, months=months)
    return ts.date()


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class EmployeeIngestor:
    """Load, clean, and map Kaggle CSV rows into employee and department records."""

    def __init__(self, csv_path: Path = CSV_PATH, as_of_date: date = AS_OF_DATE) -> None:
        self.csv_path = csv_path
        self.as_of_date = as_of_date

    def load(self) -> pd.DataFrame:
        df = pd.read_csv(self.csv_path)
        return self.clean(df)

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        required = [
            "EmployeeNumber",
            "Department",
            "JobRole",
            "MonthlyIncome",
            "Attrition",
            "YearsAtCompany",
            "YearsInCurrentRole",
            "YearsSinceLastPromotion",
            "PercentSalaryHike",
            "Gender",
        ]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"CSV missing required columns: {missing}")

        cleaned = df.drop_duplicates(subset=["EmployeeNumber"]).copy()
        cleaned["EmployeeNumber"] = cleaned["EmployeeNumber"].astype(int)
        cleaned["Department"] = cleaned["Department"].astype(str).str.strip()
        cleaned["JobRole"] = cleaned["JobRole"].astype(str).str.strip()
        cleaned["MonthlyIncome"] = cleaned["MonthlyIncome"].astype(float)
        cleaned["YearsAtCompany"] = cleaned["YearsAtCompany"].astype(int)
        cleaned["YearsInCurrentRole"] = cleaned["YearsInCurrentRole"].astype(int)
        cleaned["YearsSinceLastPromotion"] = cleaned["YearsSinceLastPromotion"].astype(int)
        cleaned["PercentSalaryHike"] = cleaned["PercentSalaryHike"].astype(int)
        cleaned["Attrition"] = cleaned["Attrition"].astype(str).str.strip()
        cleaned["Gender"] = cleaned["Gender"].astype(str).str.strip()
        return cleaned

    def _generate_identity(self, employee_number: int, gender: str) -> tuple[str, str]:
        faker = Faker()
        faker.seed_instance(employee_number)
        if gender.lower().startswith("f"):
            first = faker.first_name_female()
        elif gender.lower().startswith("m"):
            first = faker.first_name_male()
        else:
            first = faker.first_name()
        last = faker.last_name()
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}.{employee_number}@company.com"
        return name, email

    def _derive_hire_date(self, employee_number: int, years_at_company: int) -> date:
        rng = random.Random(employee_number)
        months_noise = rng.randint(-3, 3)
        years = max(years_at_company, 0)
        return _subtract_years_months(self.as_of_date, years, months_noise)

    def build_departments(self, df: pd.DataFrame) -> pd.DataFrame:
        dept_names = sorted(df["Department"].unique())
        return pd.DataFrame({"dept_name": dept_names})

    def build_employees(self, df: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for row in df.itertuples(index=False):
            employee_number = int(row.EmployeeNumber)
            name, email = self._generate_identity(employee_number, row.Gender)
            status = "Terminated" if row.Attrition.lower() == "yes" else "Active"
            rows.append(
                {
                    "employee_id": employee_number,
                    "name": name,
                    "email": email,
                    "dept_name": row.Department,
                    "hire_date": self._derive_hire_date(employee_number, row.YearsAtCompany),
                    "current_salary": _money(row.MonthlyIncome),
                    "current_role": row.JobRole,
                    "status": status,
                }
            )
        return pd.DataFrame(rows)

    def run(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        raw_df = self.load()
        departments_df = self.build_departments(raw_df)
        employees_df = self.build_employees(raw_df)
        return raw_df, departments_df, employees_df


class HistoryGenerator:
    """Construct 1–3 non-overlapping SCD2 history rows per employee."""

    def __init__(self, as_of_date: date = AS_OF_DATE) -> None:
        self.as_of_date = as_of_date

    def _history_row_count(
        self,
        years_at_company: int,
        years_in_role: int,
        years_since_promo: int,
    ) -> int:
        if years_at_company <= 1 or years_in_role >= years_at_company:
            return 1
        if years_since_promo == 0 or years_since_promo >= years_in_role:
            return 2
        return 3

    def _role_ladder_index(self, department: str, job_role: str) -> int:
        ladder = DEPT_ROLE_LADDERS.get(department, [job_role])
        normalized = ROLE_ALIASES.get(job_role, job_role)
        if normalized in ladder:
            return ladder.index(normalized)
        if job_role in ladder:
            return ladder.index(job_role)
        return max(len(ladder) - 1, 0)

    def _roles_for_history(
        self,
        department: str,
        current_role: str,
        row_count: int,
    ) -> list[str]:
        ladder = DEPT_ROLE_LADDERS.get(department, [current_role])
        current_idx = self._role_ladder_index(department, current_role)
        roles: list[str] = []
        for step in range(row_count):
            idx = max(0, current_idx - (row_count - 1 - step))
            roles.append(ladder[idx])
        roles[-1] = current_role
        return roles

    def _salaries_for_history(
        self,
        current_salary: Decimal,
        percent_hike: int,
        row_count: int,
    ) -> list[Decimal]:
        hike_pct = max(percent_hike, 3)
        factor = Decimal(str(1 + hike_pct / 100))
        salaries = [current_salary]
        for _ in range(row_count - 1):
            prior = (salaries[0] / factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            salaries.insert(0, prior)
        return salaries

    def _offset_date(self, employee_id: int, years: int, salt: int) -> date:
        rng = random.Random(employee_id + salt)
        months_noise = rng.randint(-2, 2)
        return _subtract_years_months(self.as_of_date, max(years, 0), months_noise)

    def _build_intervals(
        self,
        employee_id: int,
        hire_date: date,
        years_at_company: int,
        years_in_role: int,
        years_since_promo: int,
        row_count: int,
    ) -> list[tuple[date, date | None]]:
        if row_count == 1:
            return [(hire_date, None)]

        current_role_start = self._offset_date(employee_id, years_in_role, salt=101)
        current_role_start = max(current_role_start, hire_date)

        if row_count == 2:
            if current_role_start <= hire_date:
                current_role_start = hire_date + timedelta(days=1)
            return [
                (hire_date, current_role_start - timedelta(days=1)),
                (current_role_start, None),
            ]

        promo_date = self._offset_date(employee_id, years_since_promo, salt=202)
        promo_date = max(promo_date, hire_date + timedelta(days=1))
        if promo_date >= current_role_start:
            promo_date = hire_date + timedelta(days=1)
            current_role_start = max(current_role_start, promo_date + timedelta(days=1))

        if promo_date <= hire_date:
            promo_date = hire_date + timedelta(days=1)
        if current_role_start <= promo_date:
            current_role_start = promo_date + timedelta(days=1)

        return [
            (hire_date, promo_date - timedelta(days=1)),
            (promo_date, current_role_start - timedelta(days=1)),
            (current_role_start, None),
        ]

    def generate(self, raw_df: pd.DataFrame, employees_df: pd.DataFrame) -> pd.DataFrame:
        employee_lookup = employees_df.set_index("employee_id")
        history_rows: list[dict[str, Any]] = []

        for row in raw_df.itertuples(index=False):
            employee_id = int(row.EmployeeNumber)
            employee = employee_lookup.loc[employee_id]
            row_count = self._history_row_count(
                row.YearsAtCompany,
                row.YearsInCurrentRole,
                row.YearsSinceLastPromotion,
            )
            roles = self._roles_for_history(row.Department, row.JobRole, row_count)
            salaries = self._salaries_for_history(
                employee["current_salary"],
                row.PercentSalaryHike,
                row_count,
            )
            intervals = self._build_intervals(
                employee_id,
                employee["hire_date"],
                row.YearsAtCompany,
                row.YearsInCurrentRole,
                row.YearsSinceLastPromotion,
                row_count,
            )

            for idx, (role, salary, (start, end)) in enumerate(zip(roles, salaries, intervals)):
                is_current = idx == row_count - 1
                history_rows.append(
                    {
                        "employee_id": employee_id,
                        "role": role,
                        "salary": salary,
                        "effective_start": start,
                        "effective_end": end,
                        "is_current": is_current,
                    }
                )

        return pd.DataFrame(history_rows)


class ProjectGenerator:
    """Generate synthetic project records."""

    PROJECT_PREFIXES = [
        "Apollo",
        "Orion",
        "Nova",
        "Atlas",
        "Helios",
        "Vertex",
        "Pulse",
        "Summit",
        "Aurora",
        "Nimbus",
    ]
    PROJECT_SUFFIXES = [
        "Platform",
        "Migration",
        "Analytics",
        "Modernization",
        "Rollout",
        "Integration",
        "Optimization",
        "Automation",
        "Insights",
        "Enablement",
    ]

    def __init__(self, seed: int = 42, as_of_date: date = AS_OF_DATE) -> None:
        self.seed = seed
        self.as_of_date = as_of_date

    def generate(self, count: int = 50) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []

        for project_id in range(1, count + 1):
            rng_project = random.Random(self.seed + project_id)
            prefix = rng_project.choice(self.PROJECT_PREFIXES)
            suffix = rng_project.choice(self.PROJECT_SUFFIXES)
            project_name = f"{prefix} {suffix}"
            start_offset_days = rng_project.randint(365, 365 * 6)
            start_date = self.as_of_date - timedelta(days=start_offset_days)
            is_active = rng_project.random() < 0.35
            end_date = None
            if not is_active:
                duration_days = rng_project.randint(90, 900)
                end_date = start_date + timedelta(days=duration_days)
                if end_date > self.as_of_date:
                    end_date = self.as_of_date - timedelta(days=rng_project.randint(1, 30))
            budget = Decimal(str(rng_project.randint(50_000, 2_500_000)))

            rows.append(
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "budget": budget,
                }
            )

        return pd.DataFrame(rows)


class AssignmentGenerator:
    """Assign employees to projects with realistic allocation percentages."""

    def __init__(self, seed: int = 99, as_of_date: date = AS_OF_DATE) -> None:
        self.seed = seed
        self.as_of_date = as_of_date

    def _active_projects(self, projects_df: pd.DataFrame) -> list[int]:
        active_ids: list[int] = []
        for row in projects_df.itertuples(index=False):
            if row.end_date is None or row.end_date >= self.as_of_date:
                active_ids.append(int(row.project_id))
        return active_ids

    def _split_allocations(self, rng: random.Random, count: int) -> list[float]:
        if count == 1:
            return [float(rng.randint(40, 100))]
        if count == 2:
            first = rng.randint(25, 70)
            second = rng.randint(10, min(60, 100 - first))
            return [float(first), float(second)]
        first = rng.randint(20, 50)
        second = rng.randint(15, min(40, 100 - first - 10))
        third = float(100 - first - second)
        return [float(first), float(second), third]

    def _assignment_window(
        self,
        employee_rng: random.Random,
        hire_date: date,
        status: str,
    ) -> tuple[date, date | None]:
        tenure_days = max((self.as_of_date - hire_date).days, 1)
        start_offset = employee_rng.randint(7, min(365, max(7, tenure_days)))
        assignment_start = hire_date + timedelta(days=min(start_offset, tenure_days))
        assignment_start = min(assignment_start, self.as_of_date)

        end_date: date | None = None
        if status == "Terminated":
            days_after_start = max((self.as_of_date - assignment_start).days, 1)
            end_offset = employee_rng.randint(1, days_after_start)
            end_date = assignment_start + timedelta(days=end_offset)

        return assignment_start, end_date

    def generate(
        self,
        employees_df: pd.DataFrame,
        projects_df: pd.DataFrame,
    ) -> pd.DataFrame:
        active_project_ids = self._active_projects(projects_df)
        if not active_project_ids:
            active_project_ids = projects_df["project_id"].astype(int).tolist()

        rows: list[dict[str, Any]] = []
        assignment_id = 1

        for employee in employees_df.itertuples(index=False):
            employee_rng = random.Random(self.seed + int(employee.employee_id))
            assignment_count = employee_rng.randint(1, 3)
            chosen_projects = employee_rng.sample(
                active_project_ids,
                k=min(assignment_count, len(active_project_ids)),
            )
            allocations = self._split_allocations(employee_rng, len(chosen_projects))

            assignment_start, end_date = self._assignment_window(
                employee_rng,
                employee.hire_date,
                employee.status,
            )

            for project_id, allocation_pct in zip(chosen_projects, allocations):
                rows.append(
                    {
                        "assignment_id": assignment_id,
                        "employee_id": int(employee.employee_id),
                        "project_id": int(project_id),
                        "allocation_pct": Decimal(str(allocation_pct)),
                        "start_date": assignment_start,
                        "end_date": end_date,
                    }
                )
                assignment_id += 1

        return pd.DataFrame(rows)


class OltpLoader:
    """Write synthesized OLTP data to hr_oltp via SQLAlchemy."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def build_engine() -> Engine:
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

    def truncate_tables(self) -> None:
        statements = [
            "SET FOREIGN_KEY_CHECKS = 0",
            "TRUNCATE TABLE assignments",
            "TRUNCATE TABLE employee_history",
            "TRUNCATE TABLE employees",
            "TRUNCATE TABLE projects",
            "TRUNCATE TABLE departments",
            "SET FOREIGN_KEY_CHECKS = 1",
        ]
        with self.engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))

    def load(
        self,
        departments_df: pd.DataFrame,
        employees_df: pd.DataFrame,
        history_df: pd.DataFrame,
        projects_df: pd.DataFrame,
        assignments_df: pd.DataFrame,
    ) -> None:
        self.truncate_tables()

        departments_df.to_sql("departments", self.engine, if_exists="append", index=False)

        dept_map = pd.read_sql("SELECT dept_id, dept_name FROM departments", self.engine)
        dept_lookup = dept_map.set_index("dept_name")["dept_id"]

        employees_to_load = employees_df.copy()
        employees_to_load["dept_id"] = employees_to_load["dept_name"].map(dept_lookup)
        employees_to_load = employees_to_load.drop(columns=["dept_name"])
        employees_to_load.to_sql("employees", self.engine, if_exists="append", index=False)

        history_df.to_sql("employee_history", self.engine, if_exists="append", index=False)
        projects_df.to_sql("projects", self.engine, if_exists="append", index=False)
        assignments_df.to_sql("assignments", self.engine, if_exists="append", index=False)

    def table_counts(self) -> dict[str, int]:
        tables = ["departments", "employees", "employee_history", "projects", "assignments"]
        counts: dict[str, int] = {}
        with self.engine.connect() as conn:
            for table in tables:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = int(result.scalar_one())
        return counts

    def validate_history_current_rows(self) -> tuple[bool, pd.DataFrame]:
        query = """
            SELECT employee_id, SUM(is_current) AS current_count
            FROM employee_history
            GROUP BY employee_id
            HAVING SUM(is_current) <> 1
        """
        violations = pd.read_sql(query, self.engine)
        return violations.empty, violations


def run_pipeline() -> None:
    ingestor = EmployeeIngestor()
    raw_df, departments_df, employees_df = ingestor.run()

    history_df = HistoryGenerator().generate(raw_df, employees_df)
    projects_df = ProjectGenerator().generate(count=50)
    assignments_df = AssignmentGenerator().generate(employees_df, projects_df)

    loader = OltpLoader(OltpLoader.build_engine())
    loader.load(departments_df, employees_df, history_df, projects_df, assignments_df)

    counts = loader.table_counts()
    print("Row counts per table:")
    for table, count in counts.items():
        print(f"  {table}: {count}")

    ok, violations = loader.validate_history_current_rows()
    if ok:
        print("Sanity check: exactly one is_current=TRUE row per employee_id in employee_history.")
    else:
        print("Sanity check FAILED: employees with != 1 current history row:")
        print(violations.to_string(index=False))


if __name__ == "__main__":
    run_pipeline()
