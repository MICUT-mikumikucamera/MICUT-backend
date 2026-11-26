import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from httpx import HTTPError

import files
import store
from routers import collection
from errors import CODES
from schemas import JobError, JobResult, People, Person

KST = timezone(timedelta(hours=9))


# 명세 v0.4 예시와 같은 가짜 사람 목록
FAKE_PEOPLE = {
    "status": "ok",
    "recommended_person_id": "p0",
    "people": [
        {"person_id": "p0", "bbox_norm": [0.10, 0.15, 0.45, 0.80], "eligible": True},
        {"person_id": "p1", "bbox_norm": [0.75, 0.20, 0.82, 0.30], "eligible": False, "reason": "too_small"},
    ],
}


def detect_people(photo: bytes) -> People:
    """AI 사람 인식 결과 (people.json)."""
    # TODO(신소연): 사람 인식 AI 연결. 그 전까지는 모든 사진에 가짜 목록
    return People.model_validate(FAKE_PEOPLE)


def run_pipeline(photo: Path, out: Path, person: Person) -> JobError | None:
    command = [
        sys.executable, "-X", "utf8", os.environ["MICUT_RUN_SCRIPT"],
        "--photo", photo, "--model", os.environ["MICUT_MODEL"],
        "--blender", os.environ["BLENDER_BIN"], "--out", out,
        *(["--person", person.person_id] if person.mode == "human" else ["--solo"]),
    ]
    run = subprocess.run(command, stdout=subprocess.PIPE, encoding="utf-8", errors="replace")
    if run.returncode == 0:
        return None

    # run.py는 실행 직전에 단계 이름을 출력하고 상세 원인은 해당 단계의 로그에 남긴다.
    stages = run.stdout.splitlines()
    stage = stages[-1] if stages else ""
    labels = {"geometry": "사진 분석", "model": "모델 준비", "placement": "배치",
              "render": "렌더링", "compose": "합성"}
    if stage not in labels:
        return JobError(code="INTERNAL_ERROR", message="통합 스크립트를 실행할 수 없어요.", retryable=True)
    if stage in ("geometry", "placement"):
        with (out / f"{stage}.log").open(encoding="utf-8", errors="replace") as log:
            for line in log:
                if stage == "placement" and "NO_VALID_CANDIDATE" in line:
                    return JobError(code="NO_VALID_CANDIDATE", **CODES["NO_VALID_CANDIDATE"])
                if stage == "geometry" and "EXIF에 35mm 환산 초점거리가 없음" in line:
                    return JobError(code="INVALID_REQUEST", message="사진에 초점거리 정보가 없어요. 촬영 원본을 보내주세요.", retryable=False)
    return JobError(code="RENDER_FAILED", message=f"{labels[stage]} 단계에서 실패했어요.", retryable=True)


def read_card_id(out: Path) -> str | None:
    """AI가 정한 카드 id. 컬렉션에 없는 포즈면 None."""
    # TODO(박유진): run.py 결과에서 card_id를 읽는다. 11/19 AI 연결 때 위치(파일, 키)를 정해 채운다.
    return None


def run(job_id: str) -> None:
    """접수·재시도 뒤: 사람 인식 → (사람이 있으면 선택 대기) → 합성"""
    job = store.get_job(job_id)
    if job.status != "pending":
        return
    attempt = job.attempt
    job.status = "processing"
    job.updated_at = datetime.now(KST)
    store.save_job(job)
    if job.person is not None:  # 재시도: 고른 사람으로 다시 합성
        compose(job_id, attempt)
        return

    try:
        people = job.people or detect_people(files.load("uploads", Path(job.photo).name))
    except (OSError, ValueError, HTTPError):
        finish(job_id, attempt, JobError(code="INTERNAL_ERROR", message="사람 인식을 실행할 수 없어요.", retryable=True))
        return
    job = store.get_job(job_id)
    if job.attempt != attempt or job.status != "processing":
        return
    job.people = people
    if people.people:
        job.status = "awaiting_person"
    else:
        job.person = Person(mode="solo")
    job.updated_at = datetime.now(KST)
    store.save_job(job)
    if job.person is not None:
        compose(job_id, attempt)


def compose(job_id: str, attempt: int) -> None:
    """job.person을 따라 미쿠를 합성한다. 상태는 processing이어야 한다."""
    job = store.get_job(job_id)
    error = None
    result = None
    card_id = None
    try:
        with TemporaryDirectory(dir=".") as work:
            out = Path(work).resolve() / "output"  # run.py가 직접 생성한다.
            photo_name = Path(job.photo).name
            photo = Path(work).resolve() / photo_name
            photo.write_bytes(files.load("uploads", photo_name))
            error = run_pipeline(photo, out, job.person)

            if error is None:
                image = out / "composite" / "composite_depth.png"
                with image.open("rb") as png:
                    if png.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise ValueError("Invalid composite PNG")
                if store.get_job(job_id).attempt != attempt:
                    return
                name = f"{job_id}-{attempt}.png"
                files.save("results", name, image.read_bytes())
                result = JobResult(image_url=f"/results/{name}", tags=[], card_ids=[])
                card_id = read_card_id(out)
    except KeyError as exc:
        error = JobError(code="INTERNAL_ERROR", message=f"서버에 {exc.args[0]} 설정이 없어요.", retryable=True)
    except (OSError, ValueError, HTTPError):
        error = JobError(code="RENDER_FAILED", message="합성 실행 또는 결과 파일을 확인할 수 없어요.", retryable=True)
    finish(job_id, attempt, error, result, card_id)


def finish(job_id: str, attempt: int, error: JobError | None, result: JobResult | None = None,
           card_id: str | None = None) -> None:
    job = store.get_job(job_id)
    if job.attempt != attempt or job.status != "processing":
        return
    job.status = "failed" if error else "done"
    job.result = None if error else result
    if job.result:
        job.result.card_ids, job.result.new_card_ids = collection.award(job, card_id)
    job.error = error
    job.updated_at = datetime.now(KST)
    store.save_job(job)
