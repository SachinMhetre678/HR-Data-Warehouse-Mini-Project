-- =============================================================================
-- HR Data Warehouse — Analytical queries
-- Tables are fully qualified (hr_olap.*) so each query runs on its own in Workbench.
-- ETL must have loaded data first. Optional: USE hr_olap;
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Query 1: Tenure ranking within department (window function)
-- Business question: Who are the most tenured people in each department?
-- HR uses this for succession planning, mentoring pairs, and retention risk
-- (long-tenured staff leaving can create a knowledge gap).
-- -----------------------------------------------------------------------------
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
ORDER BY ranked.dept_name, ranked.tenure_rank;


-- -----------------------------------------------------------------------------
-- Query 2: Monthly attrition rate (CTE)
-- Business question: What percentage of staff left each month?
-- Leadership tracks this to spot worsening retention trends early and compare
-- months after policy or compensation changes.
-- -----------------------------------------------------------------------------
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
ORDER BY mh.year, mh.month;


-- -----------------------------------------------------------------------------
-- Stored procedure: see database/stored_procedures.sql
-- GetDepartmentSalaryTrend(dept_name) — department salary trend from SCD2 history
-- Example: CALL hr_olap.GetDepartmentSalaryTrend('Sales');
-- -----------------------------------------------------------------------------
