import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import store
from schemas import JobResult

KST = timezone(timedelta(hours=9))
RESULT_DIR = Path("results")
RESULT_DIR.mkdir(exist_ok=True)


# TODO(박유진): 11/5 시연용 가짜 처리. 실제 AI 연결로 바꿀 자리
def run(job_id: str) -> None:
    job = store.get_job(job_id)
    attempt = job.attempt

    time.sleep(2)
    job.status = "processing"
    job.updated_at = datetime.now(KST)
    store.save_job(job)

    time.sleep(3)
    job = store.get_job(job_id)
    if job.attempt != attempt:
        return

    photo_name = Path(job.photo).name
    shutil.copy(Path("uploads") / photo_name, RESULT_DIR / photo_name)
    job.status = "done"
    job.result = JobResult(image_url=f"/results/{photo_name}", tags=[], card_ids=[])
    job.updated_at = datetime.now(KST)
    store.save_job(job)