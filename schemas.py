from datetime import datetime
from typing import Literal

from pydantic import BaseModel

JobStatus = Literal["pending", "processing", "done", "failed"]


class Capture(BaseModel):
    w: int
    h: int
    rotation: int
    fx: float | None


class JobResult(BaseModel):
    image_url: str
    tags: list[str]
    card_ids: list[str]


class JobError(BaseModel):
    code: str
    message: str
    retryable: bool


class Job(BaseModel):
    job_id: str
    photo: str
    capture: Capture
    status: JobStatus
    attempt: int
    result: JobResult | None
    error: JobError | None
    created_at: datetime
    updated_at: datetime
