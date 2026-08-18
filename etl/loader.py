"""Load transformed data into hr_olap dimension and fact tables."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_olap_engine() -> Engine:
    load_dotenv(PROJECT_ROOT / ".env")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("OLAP_DATABASE", "hr_olap")
    if not password:
        raise ValueError(
            f"DB_PASSWORD is not set. Create {PROJECT_ROOT / '.env'} "
            "(see .env.example) with your MySQL credentials."
        )
    url = f"mysql+mysqlconnector://{user}:{password}@{host}:{port}/{database}"
    return create_engine(url)


class Loader:
    """Write OLAP dimensions and facts via SQLAlchemy + pandas."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or build_olap_engine()

    def read_dim_employee(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM dim_employee", self.engine)

    def read_dim_department(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM dim_department", self.engine)

    def read_dim_project(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM dim_project", self.engine)

    def read_dim_date(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM dim_date", self.engine)

    def load_dim_date(self, dim_date_df: pd.DataFrame) -> int:
        if dim_date_df.empty:
            return 0
        existing = self.read_dim_date()
        new_rows = dim_date_df[
            ~dim_date_df["date_key"].isin(existing["date_key"])
        ]
        if new_rows.empty:
            return 0
        new_rows.to_sql("dim_date", self.engine, if_exists="append", index=False)
        return len(new_rows)

    def load_dim_department(self, dim_department_df: pd.DataFrame) -> int:
        if dim_department_df.empty:
            return 0
        existing = self.read_dim_department()
        new_rows = dim_department_df[
            ~dim_department_df["dept_name"].isin(existing["dept_name"])
        ]
        if new_rows.empty:
            return 0
        new_rows.to_sql("dim_department", self.engine, if_exists="append", index=False)
        return len(new_rows)

    def load_dim_project(self, dim_project_df: pd.DataFrame) -> int:
        if dim_project_df.empty:
            return 0
        existing = self.read_dim_project()
        merged = dim_project_df.merge(
            existing,
            on="project_name",
            how="left",
            suffixes=("", "_existing"),
        )
        new_rows = merged[merged["project_key"].isna()][
            ["project_name", "budget"]
        ]
        if not new_rows.empty:
            new_rows.to_sql("dim_project", self.engine, if_exists="append", index=False)

        updates = merged[merged["project_key"].notna()]
        updated = 0
        with self.engine.begin() as conn:
            for row in updates.itertuples(index=False):
                conn.execute(
                    text(
                        """
                        UPDATE dim_project
                        SET budget = :budget
                        WHERE project_key = :project_key
                        """
                    ),
                    {
                        "budget": row.budget,
                        "project_key": int(row.project_key),
                    },
                )
                updated += 1
        return len(new_rows) + updated

    def apply_dim_employee_changes(
        self,
        inserts_df: pd.DataFrame,
        updates_df: pd.DataFrame,
    ) -> tuple[int, int]:
        closed = 0
        if not updates_df.empty:
            with self.engine.begin() as conn:
                for row in updates_df.itertuples(index=False):
                    conn.execute(
                        text(
                            """
                            UPDATE dim_employee
                            SET effective_end = :effective_end,
                                is_current = :is_current
                            WHERE employee_key = :employee_key
                            """
                        ),
                        {
                            "effective_end": row.effective_end,
                            "is_current": bool(row.is_current),
                            "employee_key": int(row.employee_key),
                        },
                    )
                    closed += 1

        inserted = 0
        if not inserts_df.empty:
            inserts_df.to_sql("dim_employee", self.engine, if_exists="append", index=False)
            inserted = len(inserts_df)
        return inserted, closed

    def truncate_fact(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE fact_employee_performance"))

    def load_fact(self, fact_df: pd.DataFrame) -> int:
        self.truncate_fact()
        if fact_df.empty:
            return 0
        fact_df.to_sql(
            "fact_employee_performance",
            self.engine,
            if_exists="append",
            index=False,
        )
        return len(fact_df)

    def table_counts(self) -> dict[str, int]:
        tables = [
            "dim_date",
            "dim_department",
            "dim_project",
            "dim_employee",
            "fact_employee_performance",
        ]
        counts: dict[str, int] = {}
        with self.engine.connect() as conn:
            for table in tables:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = int(result.scalar_one())
        return counts
