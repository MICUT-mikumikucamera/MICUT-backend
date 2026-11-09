from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["pending", "processing", "done", "failed"]


class Crop(BaseModel):
    """최종 결과로 쓸 영역. 전송한 원본의 좌상단 (0, 0) 기준 정수 픽셀. [x, x+width) × [y, y+height)"""

    model_config = ConfigDict(strict=True)  # 875.0, "875" 같은 값은 정수로 바꾸지 않고 거절한다.

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Capture(BaseModel):
    w: int
    h: int
    rotation: int
    fx: float | None
    crop: Crop | None = None  # 2026-11-08 이전에 만든 작업에는 없다.


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
