import sqlite3

from schemas import Job

# ponytail: 연결 하나를 모든 요청이 같이 씀. 동시 요청이 많아지면 요청마다 연결하거나 다른 DB로 교체
conn = sqlite3.connect("micut.db", check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, data TEXT NOT NULL)")


def save_job(job: Job) -> None:
    conn.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job.job_id, job.model_dump_json()))
    conn.commit()


def get_job(job_id: str) -> Job | None:
    row = conn.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return Job.model_validate_json(row[0]) if row else None
