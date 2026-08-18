-- =============================================================================
-- HR Data Warehouse — OLTP schema (hr_oltp)
-- Operational source system for employees, departments, projects, and assignments.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS hr_oltp
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE hr_oltp;

-- -----------------------------------------------------------------------------
-- departments
-- -----------------------------------------------------------------------------
CREATE TABLE departments (
    dept_id     INT          NOT NULL AUTO_INCREMENT,
    dept_name   VARCHAR(100) NOT NULL,

    PRIMARY KEY (dept_id),
    UNIQUE KEY uq_departments_dept_name (dept_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- employees
-- Current-state snapshot; role/salary changes are tracked in employee_history.
-- -----------------------------------------------------------------------------
CREATE TABLE employees (
    employee_id    INT            NOT NULL AUTO_INCREMENT,
    name           VARCHAR(150)   NOT NULL,
    email          VARCHAR(255)   NOT NULL,
    dept_id        INT            NOT NULL,
    hire_date      DATE           NOT NULL,
    current_salary DECIMAL(12, 2) NOT NULL,
    current_role   VARCHAR(100)   NOT NULL,
    status         ENUM('Active', 'Terminated') NOT NULL DEFAULT 'Active',

    PRIMARY KEY (employee_id),
    UNIQUE KEY uq_employees_email (email),
    KEY idx_employees_dept_id (dept_id),

    CONSTRAINT fk_employees_dept
        FOREIGN KEY (dept_id) REFERENCES departments (dept_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- projects
-- -----------------------------------------------------------------------------
CREATE TABLE projects (
    project_id   INT            NOT NULL AUTO_INCREMENT,
    project_name VARCHAR(200)   NOT NULL,
    start_date   DATE           NOT NULL,
    end_date     DATE           NULL,
    budget       DECIMAL(14, 2) NOT NULL,

    PRIMARY KEY (project_id),
    KEY idx_projects_start_date (start_date),

    CONSTRAINT chk_projects_dates
        CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT chk_projects_budget
        CHECK (budget >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- assignments
-- Links employees to projects with allocation percentage over a date range.
-- -----------------------------------------------------------------------------
CREATE TABLE assignments (
    assignment_id  INT           NOT NULL AUTO_INCREMENT,
    employee_id    INT           NOT NULL,
    project_id     INT           NOT NULL,
    allocation_pct DECIMAL(5, 2) NOT NULL,
    start_date     DATE          NOT NULL,
    end_date       DATE          NULL,

    PRIMARY KEY (assignment_id),
    KEY idx_assignments_employee_id (employee_id),
    KEY idx_assignments_project_id (project_id),

    CONSTRAINT fk_assignments_employee
        FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_assignments_project
        FOREIGN KEY (project_id) REFERENCES projects (project_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_assignments_allocation_pct
        CHECK (allocation_pct > 0 AND allocation_pct <= 100),
    CONSTRAINT chk_assignments_dates
        CHECK (end_date IS NULL OR end_date >= start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- employee_history — SCD Type 2 (Slowly Changing Dimension)
-- Stores every version of an employee's role and salary over time.
-- On role/salary change: close the current row and insert a new one; never overwrite.
-- -----------------------------------------------------------------------------
CREATE TABLE employee_history (
    history_id       INT            NOT NULL AUTO_INCREMENT,
    employee_id      INT            NOT NULL,
    role             VARCHAR(100)   NOT NULL,
    salary           DECIMAL(12, 2) NOT NULL,
    effective_start  DATE           NOT NULL COMMENT 'SCD2: date this role/salary version became active',
    effective_end    DATE           NULL     COMMENT 'SCD2: date this version was superseded; NULL while is_current=TRUE',
    is_current       BOOLEAN        NOT NULL DEFAULT TRUE COMMENT 'SCD2: TRUE only for the active history row per employee',

    PRIMARY KEY (history_id),
    KEY idx_employee_history_employee_id (employee_id),
    KEY idx_employee_history_is_current (employee_id, is_current),

    CONSTRAINT fk_employee_history_employee
        FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT chk_employee_history_dates
        CHECK (effective_end IS NULL OR effective_end >= effective_start),
    CONSTRAINT chk_employee_history_salary
        CHECK (salary >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
