# HR Data Warehouse — Architecture & Data Flow

End-to-end flow for the HR Data Warehouse mini project.

## High-level pipeline

```mermaid
flowchart LR
    CSV["Kaggle CSV<br/>1,470 employees"]
    SYN["data_synthesizer/<br/>generate_data.py"]
    OLTP[("hr_oltp<br/>Operational DB")]
    ETL["run_etl.py<br/>Extract → Transform → Load"]
    OLAP[("hr_olap<br/>Star Schema DW")]
    APP["Streamlit App<br/>Dashboard + Add Employee"]

    CSV --> SYN
    SYN -->|"INSERT employees,<br/>history, projects"| OLTP
    OLTP --> ETL
    ETL -->|"dims + fact<br/>SCD2 sync"| OLAP
    OLAP --> APP
    OLTP -->|"Add Employee form"| OLTP
    OLTP --> ETL
```

## Phase-by-phase detail

```mermaid
flowchart TB
    subgraph Phase1["Phase 1 — Schema"]
        DDL1["database/oltp_ddl.sql"]
        DDL2["database/olap_ddl.sql"]
        DDL1 --> OLTP_T[(hr_oltp tables)]
        DDL2 --> OLAP_T[(hr_olap tables)]
    end

    subgraph Phase2["Phase 2 — Data synthesis"]
        RAW["raw/WA_Fn-UseC_-HR-Employee-Attrition.csv"]
        ING["EmployeeIngestor"]
        HIST["HistoryGenerator"]
        PROJ["ProjectGenerator"]
        ASGN["AssignmentGenerator"]
        RAW --> ING
        ING --> HIST
        ING --> PROJ
        PROJ --> ASGN
        HIST --> OLTP_T
        ASGN --> OLTP_T
    end

    subgraph Phase3["Phase 3 — ETL"]
        EXT["Extractor<br/>read hr_oltp + CSV"]
        TRN["Transformer<br/>apply_scd2_logic<br/>build_fact_table"]
        LOD["Loader<br/>write hr_olap"]
        EXT --> TRN --> LOD
        LOD --> OLAP_T
    end

    subgraph Phase4["Phase 4 — Analytics & App"]
        SQL["analytical_queries.sql<br/>stored_procedures.sql"]
        UI["app/main.py + pages"]
        OLAP_T --> SQL
        OLAP_T --> UI
        OLTP_T --> UI
    end
```

## SCD Type 2 flow (role / salary change)

When an employee is promoted in OLTP, both databases preserve history.

```mermaid
sequenceDiagram
    participant User
    participant OLTP as hr_oltp
    participant ETL as run_etl.py
    participant OLAP as hr_olap.dim_employee

    User->>OLTP: UPDATE employees (new role/salary)
    User->>OLTP: CLOSE old employee_history row<br/>(effective_end, is_current=0)
    User->>OLTP: INSERT new employee_history row<br/>(is_current=1)

    User->>ETL: python run_etl.py
    ETL->>OLAP: Compare current OLTP history vs dim row
    alt No change since last ETL
        ETL->>OLAP: Skip (idempotent — 0 inserts)
    else Role/name/start changed
        ETL->>OLAP: CLOSE old dim row (effective_end, is_current=0)
        ETL->>OLAP: INSERT new dim row (is_current=1)
    end
    ETL->>OLAP: Rebuild fact_employee_performance
```

## Star schema (hr_olap)

```mermaid
erDiagram
    dim_date ||--o{ fact_employee_performance : date_key
    dim_department ||--o{ fact_employee_performance : department_key
    dim_project ||--o{ fact_employee_performance : project_key
    dim_employee ||--o{ fact_employee_performance : employee_key

    dim_date {
        int date_key PK
        date full_date
        int month
        int quarter
        int year
    }
    dim_department {
        int department_key PK
        string dept_name
    }
    dim_project {
        int project_key PK
        string project_name
        decimal budget
    }
    dim_employee {
        int employee_key PK
        int employee_id
        string name
        string role
        boolean is_current
        date effective_start
        date effective_end
    }
    fact_employee_performance {
        bigint fact_id PK
        int employee_key FK
        int department_key FK
        int project_key FK
        int date_key FK
        decimal salary
        decimal allocation_pct
        int tenure_days
        boolean is_attrition_flag
    }
```

## OLTP tables (hr_oltp)

```mermaid
flowchart TB
    DEPT[departments]
    EMP[employees]
    EH[employee_history<br/>SCD2]
    PROJ[projects]
    ASG[assignments]

    DEPT --> EMP
    EMP --> EH
    EMP --> ASG
    PROJ --> ASG
```

## Typical run order

| Step | Command / file | Output |
|------|----------------|--------|
| 1 | `database/oltp_ddl.sql` | `hr_oltp` schema (5 tables) |
| 2 | `database/olap_ddl.sql` | `hr_olap` schema (5 tables) |
| 3 | `python data_synthesizer/generate_data.py` | ~1,470 employees in OLTP |
| 4 | `python run_etl.py` | Star schema populated |
| 5 | `database/stored_procedures.sql` | Procedures created |
| 6 | `database/analytical_queries.sql` | Ad-hoc analytics (optional) |
| 7 | `streamlit run app/main.py` | BI dashboard in browser |

After adding employees via the app, re-run step 4 to refresh the warehouse.
