"""Orchestrate OLTP → OLAP ETL: Extract → Transform → Load."""

from etl.extractor import Extractor, build_oltp_engine
from etl.loader import Loader, build_olap_engine
from etl.transformer import Transformer


def run_etl() -> None:
    oltp_engine = build_oltp_engine()
    olap_engine = build_olap_engine()

    extractor = Extractor(oltp_engine)
    transformer = Transformer()
    loader = Loader(olap_engine)

    print("=== EXTRACT ===")
    extracted = extractor.extract_all()
    for name, frame in extracted.items():
        print(f"  {name}: {len(frame)} rows")

    print("\n=== TRANSFORM (dimensions) ===")
    dim_department = transformer.build_dim_department(extracted["departments"])
    dim_project = transformer.build_dim_project(extracted["projects"])
    dim_date = transformer.build_dim_date(
        extracted["employees"],
        extracted["assignments"],
    )
    print(f"  dim_department: {len(dim_department)} rows")
    print(f"  dim_project: {len(dim_project)} rows")
    print(f"  dim_date: {len(dim_date)} rows")

    print("\n=== LOAD (reference dimensions) ===")
    date_inserted = loader.load_dim_date(dim_date)
    dept_inserted = loader.load_dim_department(dim_department)
    project_affected = loader.load_dim_project(dim_project)
    print(f"  dim_date inserted: {date_inserted}")
    print(f"  dim_department inserted: {dept_inserted}")
    print(f"  dim_project inserted/updated: {project_affected}")

    print("\n=== TRANSFORM + LOAD (dim_employee SCD2) ===")
    dim_employee_before = loader.read_dim_employee()
    inserts, updates = transformer.apply_scd2_logic(
        extracted["employees"],
        extracted["employee_history"],
        dim_employee_before,
    )
    print(f"  SCD2 rows to insert: {len(inserts)}")
    print(f"  SCD2 rows to close: {len(updates)}")
    inserted, closed = loader.apply_dim_employee_changes(inserts, updates)
    print(f"  dim_employee inserted: {inserted}")
    print(f"  dim_employee closed: {closed}")

    print("\n=== TRANSFORM (fact) ===")
    dim_employee = loader.read_dim_employee()
    dim_department_loaded = loader.read_dim_department()
    dim_project_loaded = loader.read_dim_project()
    dim_date_loaded = loader.read_dim_date()

    fact_df = transformer.build_fact_table(
        extracted["employees"],
        extracted["projects"],
        extracted["assignments"],
        extracted["attrition_attributes"],
        dim_employee,
        dim_department_loaded,
        dim_project_loaded,
        dim_date_loaded,
    )
    print(f"  fact_employee_performance: {len(fact_df)} rows")

    print("\n=== LOAD (fact) ===")
    fact_loaded = loader.load_fact(fact_df)
    print(f"  fact_employee_performance loaded: {fact_loaded}")

    print("\n=== OLAP TABLE COUNTS ===")
    for table, count in loader.table_counts().items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    run_etl()
