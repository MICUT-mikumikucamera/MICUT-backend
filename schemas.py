from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEVICE_ID = r"^[A-Za-z0-9_-]{1,64}$"  # X-Device-Id 헤더 형식

JobStatus = Literal["pending", "processing", "awaiting_person", "done", "failed"]


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
    new_card_ids: list[str] = []  # card_ids 중 이 기기가 처음 얻은 카드. 2026-11-13 이전 작업에는 없다.


class JobError(BaseModel):
    code: str
    message: str
    retryable: bool


class DetectedPerson(BaseModel):
    model_config = ConfigDict(extra="allow")  # AI가 더 보내는 필드도 그대로 전달한다.

    person_id: str
    bbox_norm: list[float]  # [왼쪽, 위, 오른쪽, 아래], 보낸 사진 크기 대비 0~1
    eligible: bool
    reason: str | None = None


class People(BaseModel):
    """AI 사람 인식 결과 (people.json)"""

    model_config = ConfigDict(extra="allow")

    status: str
    recommended_person_id: str | None = None
    people: list[DetectedPerson]


class Person(BaseModel):
    """미쿠가 따라 할 사람. solo면 아무도 따라 하지 않는다."""

    mode: Literal["human", "solo"]
    person_id: str | None = None


class Job(BaseModel):
    job_id: str
    photo: str
    capture: Capture
    status: JobStatus
    people: People | None = None  # 사람 인식 전에는 None. 2026-11-19 이전 작업에는 없다.
    person: Person | None = None  # 고르기 전에는 None
    attempt: int
    result: JobResult | None
    error: JobError | None
    created_at: datetime
    updated_at: datetime
    device_id: str | None = None  # 접수 때 받은 X-Device-Id. 응답에는 넣지 않는다.


class CollectionPhoto(BaseModel):
    job_id: str
    acquired_at: datetime


class CollectionCard(BaseModel):
    id: str
    no: int
    name: str
    photos: list[CollectionPhoto]


class Collection(BaseModel):
    acquired_count: int
    total: int
    cards: list[CollectionCard]
