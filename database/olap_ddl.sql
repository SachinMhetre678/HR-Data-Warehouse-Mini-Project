-- =============================================================================
-- HR Data Warehouse — OLAP schema (hr_olap)
-- Star schema for analytical reporting and BI dashboards.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS hr_olap
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE hr_olap;

-- -----------------------------------------------------------------------------
-- dim_date
-- Calendar dimension; date_key is YYYYMMDD for join-friendly integer keys.
-- -----------------------------------------------------------------------------
CREATE TABLE dim_date (
    date_key   INT  NOT NULL COMMENT 'YYYYMMDD integer surrogate key',
    full_date  DATE NOT NULL,
    month      TINYINT UNSIGNED NOT NULL,
    quarter    TINYINT UNSIGNED NOT NULL,
    year       SMALLINT UNSIGNED NOT NULL,

    PRIMARY KEY (date_key),
    UNIQUE KEY uq_dim_date_full_date (full_date),
    KEY idx_dim_date_year_month (year, month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- dim_department
-- -----------------------------------------------------------------------------
CREATE TABLE dim_department (
    department_key INT          NOT NULL AUTO_INCREMENT,
    dept_name      VARCHAR(100) NOT NULL,

    PRIMARY KEY (department_key),
    UNIQUE KEY uq_dim_department_dept_name (dept_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- dim_project
-- -----------------------------------------------------------------------------
CREATE TABLE dim_project (
    project_key  INT            NOT NULL AUTO_INCREMENT,
    project_name VARCHAR(200)   NOT NULL,
    budget       DECIMAL(14, 2) NOT NULL,

    PRIMARY KEY (project_key),
    KEY idx_dim_project_project_name (project_name),

    CONSTRAINT chk_dim_project_budget
        CHECK (budget >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- dim_employee — SCD Type 2 (Slowly Changing Dimension)
-- One row per employee version; role changes create new rows, not updates.
-- ETL closes the prior row (effective_end, is_current=FALSE) and inserts the new one.
-- -----------------------------------------------------------------------------
CREATE TABLE dim_employee (
    employee_key    INT          NOT NULL AUTO_INCREMENT,
    employee_id     INT          NOT NULL COMMENT 'Natural key from OLTP employees.employee_id',
    name            VARCHAR(150) NOT NULL,
    role            VARCHAR(100) NOT NULL,
    is_current      BOOLEAN      NOT NULL DEFAULT TRUE COMMENT 'SCD2: TRUE for the active dimension row per employee_id',
    effective_start DATE         NOT NULL COMMENT 'SCD2: date this employee version became valid in the warehouse',
    effective_end   DATE         NULL     COMMENT 'SCD2: date this version was closed; NULL while is_current=TRUE',

    PRIMARY KEY (employee_key),
    KEY idx_dim_employee_employee_id (employee_id),
    KEY idx_dim_employee_is_current (employee_id, is_current),

    CONSTRAINT chk_dim_employee_dates
        CHECK (effective_end IS NULL OR effective_end >= effective_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- fact_employee_performance
-- Grain: one row per employee × project × reporting date snapshot.
-- Measures sourced from OLTP + IBM HR Attrition dataset attributes.
-- -----------------------------------------------------------------------------
CREATE TABLE fact_employee_performance (
    fact_id              BIGINT         NOT NULL AUTO_INCREMENT,
    employee_key         INT            NOT NULL,
    department_key       INT            NOT NULL,
    project_key          INT            NOT NULL,
    date_key             INT            NOT NULL,
    salary               DECIMAL(12, 2) NOT NULL,
    allocation_pct       DECIMAL(5, 2)  NOT NULL,
    tenure_days          INT            NOT NULL,
    is_attrition_flag    BOOLEAN        NOT NULL DEFAULT FALSE,
    job_satisfaction     TINYINT UNSIGNED NOT NULL,
    work_life_balance    TINYINT UNSIGNED NOT NULL,
    overtime             BOOLEAN        NOT NULL DEFAULT FALSE,
    performance_rating   TINYINT UNSIGNED NOT NULL,
    distance_from_home   SMALLINT UNSIGNED NOT NULL,

    PRIMARY KEY (fact_id),
    KEY idx_fact_employee_key (employee_key),
    KEY idx_fact_department_key (department_key),
    KEY idx_fact_project_key (project_key),
    KEY idx_fact_date_key (date_key),

    CONSTRAINT fk_fact_employee
        FOREIGN KEY (employee_key) REFERENCES dim_employee (employee_key)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_fact_department
        FOREIGN KEY (department_key) REFERENCES dim_department (department_key)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_fact_project
        FOREIGN KEY (project_key) REFERENCES dim_project (project_key)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    CONSTRAINT fk_fact_date
        FOREIGN KEY (date_key) REFERENCES dim_date (date_key)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT chk_fact_salary
        CHECK (salary >= 0),
    CONSTRAINT chk_fact_allocation_pct
        CHECK (allocation_pct > 0 AND allocation_pct <= 100),
    CONSTRAINT chk_fact_tenure_days
        CHECK (tenure_days >= 0),
    CONSTRAINT chk_fact_job_satisfaction
        CHECK (job_satisfaction BETWEEN 1 AND 4),
    CONSTRAINT chk_fact_work_life_balance
        CHECK (work_life_balance BETWEEN 1 AND 4),
    CONSTRAINT chk_fact_performance_rating
        CHECK (performance_rating BETWEEN 1 AND 4),
    CONSTRAINT chk_fact_distance_from_home
        CHECK (distance_from_home >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
