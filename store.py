import os
import sqlite3
from datetime import datetime

from schemas import Job

DATABASE_URL = os.environ.get("DATABASE_URL")
CREATE_TABLE = "CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
# 컬렉션: 기기가 어떤 사진(job)으로 어떤 카드를 얻었는지. acquired_at은 ISO 문자열.
CREATE_ACQUISITIONS = """CREATE TABLE IF NOT EXISTS acquisitions (
    device_id TEXT NOT NULL, job_id TEXT NOT NULL, card_id TEXT NOT NULL, acquired_at TEXT NOT NULL,
    PRIMARY KEY (device_id, job_id, card_id))"""

if DATABASE_URL:
    # 배포 서버: Supabase PostgreSQL. 서버가 재시작돼도 기록이 남는다.
    from psycopg_pool import ConnectionPool

    # prepare_threshold=None: Supabase 연결 풀러(PgBouncer)는 prepared statement를 지원하지 않는다.
    pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": None},
        check=ConnectionPool.check_connection,
    )
    with pool.connection() as conn:
        conn.execute(CREATE_TABLE)
        conn.execute(CREATE_ACQUISITIONS)

    def save_job(job: Job) -> None:
        with pool.connection() as conn:
            conn.execute(
                "INSERT INTO jobs VALUES (%s, %s) ON CONFLICT (job_id) DO UPDATE SET data = EXCLUDED.data",
                (job.job_id, job.model_dump_json()),
            )

    def get_job(job_id: str) -> Job | None:
        with pool.connection() as conn:
            row = conn.execute("SELECT data FROM jobs WHERE job_id = %s", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def add_acquisition(device_id: str, job_id: str, card_id: str, at: datetime) -> bool:
        """기록하고, 이 기기가 그 카드를 처음 얻었으면 True."""
        with pool.connection() as conn:
            had = conn.execute(
                "SELECT 1 FROM acquisitions WHERE device_id = %s AND card_id = %s", (device_id, card_id)
            ).fetchone()
            conn.execute(
                "INSERT INTO acquisitions VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (device_id, job_id, card_id, at.isoformat()),
            )
        return had is None

    def list_acquisitions(device_id: str) -> list[tuple[str, str, str]]:
        """(card_id, job_id, acquired_at) 목록"""
        with pool.connection() as conn:
            return conn.execute(
                "SELECT card_id, job_id, acquired_at FROM acquisitions WHERE device_id = %s", (device_id,)
            ).fetchall()

else:
    # 내 PC 개발용: SQLite 파일 하나.
    # ponytail: 연결 하나를 모든 요청이 같이 씀. 동시 요청이 많아지면 요청마다 연결하거나 다른 DB로 교체
    conn = sqlite3.connect("micut.db", check_same_thread=False)
    conn.execute(CREATE_TABLE)
    conn.execute(CREATE_ACQUISITIONS)

    def save_job(job: Job) -> None:
        conn.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job.job_id, job.model_dump_json()))
        conn.commit()

    def get_job(job_id: str) -> Job | None:
        row = conn.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def add_acquisition(device_id: str, job_id: str, card_id: str, at: datetime) -> bool:
        had = conn.execute(
            "SELECT 1 FROM acquisitions WHERE device_id = ? AND card_id = ?", (device_id, card_id)
        ).fetchone()
        conn.execute("INSERT OR IGNORE INTO acquisitions VALUES (?, ?, ?, ?)", (device_id, job_id, card_id, at.isoformat()))
        conn.commit()
        return had is None

    def list_acquisitions(device_id: str) -> list[tuple[str, str, str]]:
        return conn.execute(
            "SELECT card_id, job_id, acquired_at FROM acquisitions WHERE device_id = ?", (device_id,)
        ).fetchall()
