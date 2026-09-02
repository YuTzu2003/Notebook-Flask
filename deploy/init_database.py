import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "deploy" / "database" / "script.sql"
GO_SEPARATOR = re.compile(r"(?im)^\s*GO\s*(?:--.*)?$")
load_dotenv(PROJECT_ROOT / ".env")


def load_schema_statements():
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f"Database schema file was not found: {SCHEMA_PATH}")

    schema = SCHEMA_PATH.read_text(encoding="utf-8-sig")
    if re.search(r"(?im)^\s*(USE|CREATE\s+DATABASE|ALTER\s+DATABASE)\b", schema):
        raise RuntimeError("script.sql must not select or create a database; use DATABASE_URL in .env instead.")

    statements = tuple(batch.strip() for batch in GO_SEPARATOR.split(schema) if batch.strip())
    if not statements:
        raise RuntimeError("Database schema file does not contain executable SQL.")
    return statements


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required in .env")

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        for statement in load_schema_statements():
            connection.execute(text(statement))

    print("Database schema is ready.")


if __name__ == "__main__":
    main()
