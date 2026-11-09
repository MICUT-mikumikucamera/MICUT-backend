"""접수 → 처리 → 재시도 → discard 흐름 확인. 실행: python test_flow.py

프로젝트의 micut.db, uploads/를 건드리지 않도록 임시 폴더에서 돌린다.
"""
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.pop(name, None)  # 항상 내 PC 모드(SQLite, 폴더)로 시험한다.
tmp = tempfile.mkdtemp()
shutil.copytree(ROOT / "contracts", Path(tmp) / "contracts")
os.chdir(tmp)
sys.path.insert(0, str(ROOT))

import io  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import fake_ai  # noqa: E402
import store  # noqa: E402
from main import app  # noqa: E402
from schemas import Job, JobError  # noqa: E402

fake_ai.time.sleep = lambda seconds: None
c = TestClient(app)
buf = io.BytesIO()
Image.new("RGB", (40, 30)).save(buf, "JPEG")
JPG = buf.getvalue()
CROP = '{"x":10,"y":0,"width":22,"height":30}'
FIELDS = {"w": "40", "h": "30", "rotation": "0", "crop": CROP}


def post(photo=JPG, **changes):
    data = {k: v for k, v in {**FIELDS, **changes}.items() if v is not None}
    return c.post("/api/v1/jobs", files={"photo": ("a.jpg", photo, "image/jpeg")}, data=data)


def submit():
    r = post()
    assert r.status_code == 201, r.text
    return r.json()["job_id"]


# crop은 응답 capture에 그대로 남는다
r = post()
assert r.status_code == 201, r.text
assert r.json()["capture"] == {"w": 40, "h": 30, "rotation": 0, "fx": None,
                               "crop": {"x": 10, "y": 0, "width": 22, "height": 30}}

# 잘못된 접수는 자동 보정 없이 422 INVALID_REQUEST
for bad in [
    {"crop": None},                                          # crop 없음
    {"crop": "not json"},
    {"crop": '"{\\"x\\":10,\\"y\\":0,\\"width\\":22,\\"height\\":30}"'},  # 이중 인코딩
    {"crop": '{"x":10.5,"y":0,"width":22,"height":30}'},     # 정수 아님
    {"crop": '{"x":"10","y":0,"width":22,"height":30}'},
    {"crop": '{"x":-1,"y":0,"width":22,"height":30}'},
    {"crop": '{"x":10,"y":0,"width":0,"height":30}'},
    {"crop": '{"x":19,"y":0,"width":22,"height":30}'},       # 오른쪽 밖 (19+22 > 40)
    {"crop": '{"x":0,"y":1,"width":22,"height":30}'},        # 아래쪽 밖
    {"w": "30", "h": "40"},                                  # 실제 크기와 다름
    {"rotation": "90"},
]:
    r = post(**bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", (bad, r.text)
assert post(crop='{"x":0,"y":0,"width":40,"height":30}').status_code == 201  # 사진 전체
r = post(photo=b"\xff\xd8\xff\xe0" + b"0" * 100)                       # JPEG 머리만 있고 깨진 파일
assert r.status_code == 400 and r.json()["error"]["code"] == "UPLOAD_INVALID_FORMAT"

# crop이 없는 예전 작업도 읽힌다
old = Job.model_validate_json(store.get_job(submit()).model_dump_json(exclude={"capture": {"crop"}}))
assert old.capture.crop is None


def make_failed(job_id, retryable=True, hours_ago=0):
    job = store.get_job(job_id)
    job.status = "failed"
    job.result = None
    job.error = JobError(code="AI_TIMEOUT", message="처리가 오래 걸렸어요", retryable=retryable)
    job.updated_at -= timedelta(hours=hours_ago)
    store.save_job(job)


def photo_exists(job_id):
    return any(Path("uploads").glob(f"{job_id}.*"))


# done이 되면 crop 영역만 잘린 결과가 열리고 원본은 지워진다
jid = submit()
job = c.get(f"/api/v1/jobs/{jid}").json()
assert job["status"] == "done"
assert job["capture"]["crop"] == {"x": 10, "y": 0, "width": 22, "height": 30}
assert Image.open(io.BytesIO(c.get(job["result"]["image_url"]).content)).size == (22, 30)
assert not photo_exists(jid)

# 재시도: failed + retryable → pending, attempt +1, error 비움 → 다시 처리되어 done
jid = submit()
make_failed(jid)
r = c.post(f"/api/v1/jobs/{jid}/retry")
assert r.status_code == 200 and r.json()["status"] == "pending"
assert r.json()["attempt"] == 2 and r.json()["error"] is None
assert c.get(f"/api/v1/jobs/{jid}").json()["status"] == "done"

# 재시도 불가: done 작업, retryable false 실패, 없는 작업
assert c.post(f"/api/v1/jobs/{jid}/retry").json()["error"]["code"] == "RETRY_NOT_ALLOWED"
jid = submit()
make_failed(jid, retryable=False)
r = c.post(f"/api/v1/jobs/{jid}/retry")
assert r.status_code == 409 and r.json()["error"]["code"] == "RETRY_NOT_ALLOWED"
assert not photo_exists(jid)
assert c.post("/api/v1/jobs/nope/retry").status_code == 404

# discard: 204, retryable → false, 원본 삭제, 이후 재시도 불가
jid = submit()
make_failed(jid)
assert photo_exists(jid)
r = c.post(f"/api/v1/jobs/{jid}/discard")
assert r.status_code == 204 and r.content == b""
assert c.get(f"/api/v1/jobs/{jid}").json()["error"]["retryable"] is False
assert not photo_exists(jid)
assert c.post(f"/api/v1/jobs/{jid}/retry").status_code == 409

# 24시간 지난 retryable 실패는 조회 시 discard 처리된다
jid = submit()
make_failed(jid, hours_ago=25)
assert c.get(f"/api/v1/jobs/{jid}").json()["error"]["retryable"] is False
assert not photo_exists(jid)

# 24시간 전이면 그대로 재시도 가능
jid = submit()
make_failed(jid, hours_ago=23)
assert c.post(f"/api/v1/jobs/{jid}/retry").status_code == 200

store.conn.close()
os.chdir(ROOT)
shutil.rmtree(tmp, ignore_errors=True)
print("ok")
