"""Transform OLTP extracts into OLAP dimension and fact datasets."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

AS_OF_DATE = date(2024, 1, 1)


def _date_to_key(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Transformer:
    """Build OLAP dimensions and the employee performance fact table."""

    def __init__(self, as_of_date: date = AS_OF_DATE) -> None:
        self.as_of_date = as_of_date
        self.as_of_date_key = _date_to_key(as_of_date)

    def build_dim_department(self, departments_df: pd.DataFrame) -> pd.DataFrame:
        return departments_df[["dept_name"]].drop_duplicates().sort_values("dept_name")

    def build_dim_project(self, projects_df: pd.DataFrame) -> pd.DataFrame:
        return projects_df[["project_name", "budget"]].drop_duplicates(
            subset=["project_name"]
        )

    def build_dim_date(
        self,
        employees_df: pd.DataFrame,
        assignments_df: pd.DataFrame,
    ) -> pd.DataFrame:
        dates: set[date] = {self.as_of_date}
        for hire_date in employees_df["hire_date"]:
            dates.add(pd.Timestamp(hire_date).date())
        for column in ("start_date", "end_date"):
            for value in assignments_df[column].dropna():
                dates.add(pd.Timestamp(value).date())

        rows: list[dict[str, Any]] = []
        for full_date in sorted(dates):
            ts = pd.Timestamp(full_date)
            rows.append(
                {
                    "date_key": _date_to_key(full_date),
                    "full_date": full_date,
                    "month": int(ts.month),
                    "quarter": int((ts.month - 1) // 3 + 1),
                    "year": int(ts.year),
                }
            )
        return pd.DataFrame(rows)

    def apply_scd2_logic(
        self,
        employees_df: pd.DataFrame,
        employee_history_df: pd.DataFrame,
        dim_employee_df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Sync dim_employee with OLTP current history rows.

        Idempotent: unchanged OLTP data produces zero inserts and zero closes.
        On role/name/effective_start change, close the current dim row and insert a new one.
        """
        current_history = employee_history_df.loc[
            employee_history_df["is_current"] == True  # noqa: E712
        ].copy()
        current_history = current_history.merge(
            employees_df[["employee_id", "name"]],
            on="employee_id",
            how="inner",
        )

        inserts: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []

        for row in current_history.itertuples(index=False):
            dim_current = dim_employee_df.loc[
                (dim_employee_df["employee_id"] == row.employee_id)
                & (dim_employee_df["is_current"] == True)  # noqa: E712
            ]

            effective_start = pd.Timestamp(row.effective_start).date()
            if dim_current.empty:
                inserts.append(
                    {
                        "employee_id": int(row.employee_id),
                        "name": row.name,
                        "role": row.role,
                        "is_current": True,
                        "effective_start": effective_start,
                        "effective_end": None,
                    }
                )
                continue

            dim_row = dim_current.iloc[0]
            dim_effective_start = pd.Timestamp(dim_row["effective_start"]).date()
            if (
                dim_row["name"] == row.name
                and dim_row["role"] == row.role
                and dim_effective_start == effective_start
            ):
                continue

            close_date = effective_start - timedelta(days=1)
            updates.append(
                {
                    "employee_key": int(dim_row["employee_key"]),
                    "effective_end": close_date,
                    "is_current": False,
                }
            )
            inserts.append(
                {
                    "employee_id": int(row.employee_id),
                    "name": row.name,
                    "role": row.role,
                    "is_current": True,
                    "effective_start": effective_start,
                    "effective_end": None,
                }
            )

        return pd.DataFrame(inserts), pd.DataFrame(updates)

    def build_fact_table(
        self,
        employees_df: pd.DataFrame,
        projects_df: pd.DataFrame,
        assignments_df: pd.DataFrame,
        attrition_df: pd.DataFrame,
        dim_employee_df: pd.DataFrame,
        dim_department_df: pd.DataFrame,
        dim_project_df: pd.DataFrame,
        dim_date_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Grain: employee x project x as-of snapshot date."""
        employee_keys = dim_employee_df.loc[
            dim_employee_df["is_current"] == True  # noqa: E712
        ][["employee_key", "employee_id"]]

        assignment_enriched = assignments_df.merge(
            projects_df[["project_id", "project_name"]],
            on="project_id",
            how="left",
        )
        assignment_enriched = assignment_enriched.merge(
            employees_df[
                [
                    "employee_id",
                    "dept_name",
                    "hire_date",
                    "current_salary",
                    "status",
                ]
            ],
            on="employee_id",
            how="left",
        )
        assignment_enriched = assignment_enriched.merge(
            employee_keys,
            on="employee_id",
            how="inner",
        )
        assignment_enriched = assignment_enriched.merge(
            dim_department_df[["department_key", "dept_name"]],
            on="dept_name",
            how="left",
        )
        assignment_enriched = assignment_enriched.merge(
            dim_project_df[["project_key", "project_name"]],
            on="project_name",
            how="left",
        )

        if self.as_of_date_key not in set(dim_date_df["date_key"].tolist()):
            raise ValueError(
                f"as_of_date_key {self.as_of_date_key} missing from dim_date"
            )

        attrition = attrition_df.copy()
        attrition["is_attrition_flag"] = attrition["Attrition"].str.lower().eq("yes")
        attrition["overtime"] = attrition["OverTime"].str.lower().eq("yes")
        attrition = attrition.rename(
            columns={
                "JobSatisfaction": "job_satisfaction",
                "WorkLifeBalance": "work_life_balance",
                "PerformanceRating": "performance_rating",
                "DistanceFromHome": "distance_from_home",
            }
        )

        fact = assignment_enriched.merge(
            attrition[
                [
                    "employee_id",
                    "is_attrition_flag",
                    "job_satisfaction",
                    "work_life_balance",
                    "overtime",
                    "performance_rating",
                    "distance_from_home",
                ]
            ],
            on="employee_id",
            how="left",
        )

        hire_dates = pd.to_datetime(fact["hire_date"]).dt.date
        fact["tenure_days"] = [
            max((self.as_of_date - hire).days, 0) for hire in hire_dates
        ]
        fact["salary"] = fact["current_salary"].apply(_money)
        fact["allocation_pct"] = fact["allocation_pct"].apply(
            lambda value: Decimal(str(value)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        fact["date_key"] = self.as_of_date_key

        fact = fact.dropna(
            subset=["employee_key", "department_key", "project_key"]
        )

        return fact[
            [
                "employee_key",
                "department_key",
                "project_key",
                "date_key",
                "salary",
                "allocation_pct",
                "tenure_days",
                "is_attrition_flag",
                "job_satisfaction",
                "work_life_balance",
                "overtime",
                "performance_rating",
                "distance_from_home",
            ]
        ]
