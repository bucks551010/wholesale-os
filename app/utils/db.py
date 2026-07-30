import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL")

if not _DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")


def get_connection():
    return psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


@contextmanager
def db_cursor(commit: bool = False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(sql: str, params=None, *, commit: bool = True) -> list[dict]:
    with db_cursor(commit=commit) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except psycopg2.ProgrammingError:
            return []


def execute_many(sql: str, params_list: list, *, commit: bool = True) -> int:
    with db_cursor(commit=commit) as cur:
        psycopg2.extras.execute_batch(cur, sql, params_list, page_size=500)
        return cur.rowcount
