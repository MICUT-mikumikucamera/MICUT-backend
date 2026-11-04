import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import store
from errors import CODES
from schemas import JobError, JobResult

KST = timezone(timedelta(hours=9))
RESULT_DIR = Path("results")
RESULT_DIR.mkdir(exist_ok=True)


def run_pipeline(photo: Path, out: Path) -> JobError | None:
    command = [
        sys.executable, "-X", "utf8", os.environ["MICUT_RUN_SCRIPT"],
        "--photo", photo, "--model", os.environ["MICUT_MODEL"],
        "--blender", os.environ["BLENDER_BIN"], "--out", out,
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


def run(job_id: str) -> None:
    job = store.get_job(job_id)
    attempt = job.attempt

    job = store.get_job(job_id)
    if job.attempt != attempt or job.status != "pending":
        return
    job.status = "processing"
    job.updated_at = datetime.now(KST)
    store.save_job(job)

    error = None
    result = None
    try:
        with TemporaryDirectory(dir=".") as work:
            out = Path(work).resolve() / "output"  # run.py가 직접 생성한다.
            photo = (Path("uploads") / Path(job.photo).name).resolve()
            error = run_pipeline(photo, out)

            if error is None:
                image = out / "composite" / "composite_depth.png"
                with image.open("rb") as png:
                    if png.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise ValueError("Invalid composite PNG")
                if store.get_job(job_id).attempt != attempt:
                    return
                name = f"{job_id}-{attempt}.png"
                image.replace(RESULT_DIR / name)
                result = JobResult(image_url=f"/results/{name}", tags=[], card_ids=[])
    except KeyError as exc:
        error = JobError(code="INTERNAL_ERROR", message=f"서버에 {exc.args[0]} 설정이 없어요.", retryable=True)
    except (OSError, ValueError):
        error = JobError(code="RENDER_FAILED", message="합성 실행 또는 결과 파일을 확인할 수 없어요.", retryable=True)

    job = store.get_job(job_id)
    if job.attempt != attempt or job.status != "processing":
        return
    job.status = "failed" if error else "done"
    job.result = None if error else result
    job.error = error
    job.updated_at = datetime.now(KST)
    store.save_job(job)
