import io
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

import files
import store
from schemas import JobResult

KST = timezone(timedelta(hours=9))


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
    data = files.load("uploads", photo_name)
    crop = job.capture.crop
    if crop:  # 실제 AI처럼 결과는 crop 영역만 내보낸다.
        image = Image.open(io.BytesIO(data))
        out = io.BytesIO()
        image.crop((crop.x, crop.y, crop.x + crop.width, crop.y + crop.height)).save(out, image.format, quality=95)
        data = out.getvalue()
    files.save("results", photo_name, data)
    job.status = "done"
    job.result = JobResult(image_url=f"/results/{photo_name}", tags=[], card_ids=[])
    job.updated_at = datetime.now(KST)
    store.save_job(job)
