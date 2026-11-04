import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import store
from errors import CODES
from schemas import JobError, JobResult

KST = timezone(timedelta(hours=9))
RESULT_DIR = Path("results")
RESULT_DIR.mkdir(exist_ok=True)
SAMPLE_CASE = os.getenv("MICUT_SAMPLE_CASE", "success")
if SAMPLE_CASE not in ("success", "no-placement"):
    raise ValueError("MICUT_SAMPLE_CASE must be success or no-placement")


# TODO(박유진): 11/5 시연용 가짜 처리. 실제 AI 연결로 바꿀 자리
def run(job_id: str) -> None:
    job = store.get_job(job_id)
    attempt = job.attempt

    time.sleep(2)
    job.status = "processing"
    job.updated_at = datetime.now(KST)
    store.save_job(job)

    time.sleep(13)
    job = store.get_job(job_id)
    if job.attempt != attempt:
        return

    if SAMPLE_CASE == "no-placement":
        job.status = "failed"
        job.result = None
        job.error = JobError(code="NO_VALID_CANDIDATE", **CODES["NO_VALID_CANDIDATE"])
    else:
        name = f"{job_id}.png"
        shutil.copyfile(Path(__file__).with_name("samples") / "cafe-composite.png", RESULT_DIR / name)
        job.status = "done"
        job.result = JobResult(image_url=f"/results/{name}", tags=[], card_ids=[])
    job.updated_at = datetime.now(KST)
    store.save_job(job)
