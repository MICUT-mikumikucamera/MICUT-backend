import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, UploadFile

import fake_ai
import store
from errors import AppError
from schemas import Capture, Job

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

KST = timezone(timedelta(hours=9))
MAX_SIZE = 10 * 1024 * 1024
DISCARD_AFTER = timedelta(hours=24)
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def delete_photo(job: Job) -> None:
    (UPLOAD_DIR / Path(job.photo).name).unlink(missing_ok=True)


def discard(job: Job) -> None:
    job.error.retryable = False
    job.updated_at = datetime.now(KST)
    store.save_job(job)
    delete_photo(job)


# ponytail: 24시간 discard는 그 작업을 조회할 때만 확인함. 다시 안 오는 작업의 원본은 남으니, 실제 AI가 실패를 내기 시작하면 주기적 정리 추가
def load_job(job_id: str) -> Job:
    job = store.get_job(job_id)
    if job is None:
        raise AppError("JOB_NOT_FOUND")
    if job.status == "failed" and job.error.retryable and datetime.now(KST) - job.updated_at > DISCARD_AFTER:
        discard(job)
    if job.status == "done" or (job.status == "failed" and not job.error.retryable):
        delete_photo(job)
    return job


@router.post("", response_model=Job, status_code=201)
def create_job(
    photo: UploadFile,
    background_tasks: BackgroundTasks,
    w: int = Form(),
    h: int = Form(),
    rotation: int = Form(),
    fx: float | None = Form(None),
):
    data = photo.file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise AppError("UPLOAD_TOO_LARGE")
    if data.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    else:
        raise AppError("UPLOAD_INVALID_FORMAT")

    now = datetime.now(KST)
    job_id = f"j_{now:%Y%m%d}_{secrets.token_hex(6)}"
    (UPLOAD_DIR / f"{job_id}{ext}").write_bytes(data)

    job = Job(
        job_id=job_id,
        photo=f"/uploads/{job_id}{ext}",
        capture=Capture(w=w, h=h, rotation=rotation, fx=fx),
        status="pending",
        attempt=1,
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
    )
    store.save_job(job)
    # TODO(박유진): 시연이 끝나면 fake_ai.run 대신 실제 AI 처리를 시작
    background_tasks.add_task(fake_ai.run, job_id)
    return job


@router.get("/{job_id}", response_model=Job)
def read_job(job_id: str):
    return load_job(job_id)


@router.post("/{job_id}/retry", response_model=Job)
def retry_job(job_id: str, background_tasks: BackgroundTasks):
    job = load_job(job_id)
    if job.status != "failed" or not job.error.retryable:
        raise AppError("RETRY_NOT_ALLOWED")
    job.status = "pending"
    job.error = None
    job.attempt += 1
    job.updated_at = datetime.now(KST)
    store.save_job(job)
    # TODO(박유진): 시연이 끝나면 fake_ai.run 대신 실제 AI 처리를 시작
    background_tasks.add_task(fake_ai.run, job_id)
    return job


@router.post("/{job_id}/discard", status_code=204)
def discard_job(job_id: str):
    job = load_job(job_id)
    if job.status == "failed" and job.error.retryable:
        discard(job)
