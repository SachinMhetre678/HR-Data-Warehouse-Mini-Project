-- =============================================================================
-- HR Data Warehouse — Stored procedures (hr_olap)
-- Run in MySQL Workbench after OLTP + OLAP schemas exist and data is loaded.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- GetDepartmentSalaryTrend(dept_name)
-- Business question: How has average pay evolved for a department over time?
-- Uses OLTP employee_history (SCD2 role/salary versions) joined to departments.
-- -----------------------------------------------------------------------------
DROP PROCEDURE IF EXISTS hr_olap.GetDepartmentSalaryTrend;

DELIMITER //

CREATE PROCEDURE hr_olap.GetDepartmentSalaryTrend(IN p_dept_name VARCHAR(100))
BEGIN
    SELECT
        d.dept_name,
        DATE_FORMAT(eh.effective_start, '%Y-%m') AS salary_month,
        eh.role,
        COUNT(*) AS employee_versions,
        ROUND(AVG(eh.salary), 2) AS avg_salary,
        ROUND(MIN(eh.salary), 2) AS min_salary,
        ROUND(MAX(eh.salary), 2) AS max_salary
    FROM hr_oltp.employee_history AS eh
    INNER JOIN hr_oltp.employees AS e
        ON eh.employee_id = e.employee_id
    INNER JOIN hr_oltp.departments AS d
        ON e.dept_id = d.dept_id
    WHERE d.dept_name = p_dept_name
    GROUP BY
        d.dept_name,
        DATE_FORMAT(eh.effective_start, '%Y-%m'),
        eh.role
    ORDER BY salary_month, eh.role;
END //

DELIMITER ;

-- Example:
-- CALL hr_olap.GetDepartmentSalaryTrend('Sales');
-- CALL hr_olap.GetDepartmentSalaryTrend('Research & Development');
