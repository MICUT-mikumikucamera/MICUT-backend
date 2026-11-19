import io
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Form, Header, UploadFile
from PIL import Image
from pydantic import ValidationError

import fake_ai
import files
import store
from errors import AppError
from schemas import DEVICE_ID, Capture, Crop, Job

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

KST = timezone(timedelta(hours=9))
MAX_SIZE = 10 * 1024 * 1024
DISCARD_AFTER = timedelta(hours=24)
HIDDEN = {"device_id"}  # 작업 응답에 기기 ID는 내보내지 않는다.


def delete_photo(job: Job) -> None:
    files.delete("uploads", Path(job.photo).name)


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


@router.post("", response_model=Job, response_model_exclude=HIDDEN, status_code=201)
def create_job(
    photo: UploadFile,
    background_tasks: BackgroundTasks,
    w: int = Form(),
    h: int = Form(),
    rotation: int = Form(),
    fx: float | None = Form(None),
    crop: str = Form(),  # JSON 텍스트. Json[Crop]으로 받으면 FastAPI가 폼 필드 x, y, ...로 착각한다.
    x_device_id: Annotated[str | None, Header(pattern=DEVICE_ID)] = None,
):
    try:
        crop = Crop.model_validate_json(crop)
    except ValidationError:
        raise AppError("INVALID_REQUEST")
    data = photo.file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise AppError("UPLOAD_TOO_LARGE")
    if data.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    else:
        raise AppError("UPLOAD_INVALID_FORMAT")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()  # 끝까지 디코딩해서 잘린·깨진 파일을 여기서 거른다.
            size = image.size
    except (OSError, Image.DecompressionBombError):
        raise AppError("UPLOAD_INVALID_FORMAT")
    # 프런트가 EXIF 방향을 픽셀에 적용해서 보내므로 rotation은 항상 0이고, 서버는 회전하지 않는다.
    if size != (w, h) or rotation != 0 or crop.x + crop.width > w or crop.y + crop.height > h:
        raise AppError("INVALID_REQUEST")

    now = datetime.now(KST)
    job_id = f"j_{now:%Y%m%d}_{secrets.token_hex(6)}"
    files.save("uploads", f"{job_id}{ext}", data)

    job = Job(
        job_id=job_id,
        photo=f"/uploads/{job_id}{ext}",
        capture=Capture(w=w, h=h, rotation=rotation, fx=fx, crop=crop),
        status="pending",
        attempt=1,
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
        device_id=x_device_id,
    )
    store.save_job(job)
    # TODO(박유진): 시연이 끝나면 fake_ai.run 대신 실제 AI 처리를 시작
    background_tasks.add_task(fake_ai.run, job_id)
    return job


@router.get("/{job_id}", response_model=Job, response_model_exclude=HIDDEN)
def read_job(job_id: str):
    return load_job(job_id)


@router.post("/{job_id}/retry", response_model=Job, response_model_exclude=HIDDEN)
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
