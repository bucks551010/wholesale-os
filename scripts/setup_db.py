"""
Run once to create all database tables.
Usage: python scripts/setup_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.utils.db import get_connection

MIGRATION_FILE = os.path.join(
    os.path.dirname(__file__), "..", "db", "migrations", "001_initial_schema.sql"
)


def run():
    print("Connecting to database...")
    conn = get_connection()
    cur = conn.cursor()

    print("Running schema migration...")
    with open(MIGRATION_FILE, "r") as f:
        sql = f.read()

    cur.execute(sql)
    conn.commit()
    conn.close()
    print("✅ Schema created successfully.")


if __name__ == "__main__":
    run()
