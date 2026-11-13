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

c = TestClient(app)
buf = io.BytesIO()
Image.new("RGB", (40, 30)).save(buf, "JPEG")
JPG = buf.getvalue()
CROP = '{"x":10,"y":0,"width":22,"height":30}'
FIELDS = {"w": "40", "h": "30", "rotation": "0", "crop": CROP}


def post(photo=JPG, **changes):
    data = {k: v for k, v in {**FIELDS, **changes}.items() if v is not None}
    return c.post("/api/v1/jobs", files={"photo": ("a.jpg", photo, "image/jpeg")}, data=data)


# API 흐름 테스트에서는 외부 AI 대신 테스트용 합성 결과를 쓴다.
def stub_pipeline(photo, out):
    assert photo.read_bytes() == JPG
    image = out / "composite" / "composite_depth.png"
    image.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "samples" / "cafe-composite.png", image)


fake_ai.run_pipeline = stub_pipeline


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


# done이 되면 결과가 열리고 원본은 지워진다. 조회 응답에도 crop이 남는다.
jid = submit()
job = c.get(f"/api/v1/jobs/{jid}").json()
assert job["status"] == "done"
assert job["capture"]["crop"] == {"x": 10, "y": 0, "width": 22, "height": 30}
assert c.get(job["result"]["image_url"]).content == (ROOT / "samples" / "cafe-composite.png").read_bytes()
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

# 컬렉션: done이 되면 서버가 카드 1장을 정하고, X-Device-Id를 보낸 기기의 컬렉션에 기록한다
DEV = {"X-Device-Id": "dev-a"}


def submit_as(headers):
    r = c.post("/api/v1/jobs", files={"photo": ("a.jpg", JPG, "image/jpeg")}, data=FIELDS, headers=headers)
    assert r.status_code == 201, r.text
    assert "device_id" not in r.json()                      # 기기 ID는 응답에 안 나간다
    return c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()


empty = c.get("/api/v1/collection", headers=DEV).json()
assert empty["total"] == 12 and empty["acquired_count"] == 0
assert [card["no"] for card in empty["cards"]] == list(range(1, 13))

first = submit_as(DEV)
assert "device_id" not in first
card = first["result"]["card_ids"]
assert len(card) == 1 and first["result"]["new_card_ids"] == card     # 첫 카드는 신규

# 카드는 12장이라 13번 안에 반드시 같은 카드가 다시 나온다 → 신규 아님, 사진만 쌓인다
seen = {card[0]: [first["job_id"]]}
for _ in range(13):
    job = submit_as(DEV)
    cid = job["result"]["card_ids"][0]
    assert job["result"]["new_card_ids"] == ([] if cid in seen else [cid])
    seen.setdefault(cid, []).append(job["job_id"])
col = c.get("/api/v1/collection", headers=DEV).json()
assert col["acquired_count"] == len(seen)
for entry in col["cards"]:
    assert [ph["job_id"] for ph in entry["photos"]] == seen.get(entry["id"], [])

# 다른 기기와는 섞이지 않고, 헤더 없이 찍으면 카드는 정해지지만 기록되지 않는다
assert c.get("/api/v1/collection", headers={"X-Device-Id": "dev-b"}).json()["acquired_count"] == 0
anon = submit_as({})
assert len(anon["result"]["card_ids"]) == 1 and anon["result"]["new_card_ids"] == []

# 기기 ID가 없거나 형식이 틀리면 422
assert c.get("/api/v1/collection").json()["error"]["code"] == "INVALID_REQUEST"
for bad in ["", "a b", "x" * 65, "a/b"]:
    assert c.get("/api/v1/collection", headers={"X-Device-Id": bad}).status_code == 422, bad
r = c.post("/api/v1/jobs", files={"photo": ("a.jpg", JPG, "image/jpeg")}, data=FIELDS, headers={"X-Device-Id": "a b"})
assert r.status_code == 422

store.conn.close()
os.chdir(ROOT)
shutil.rmtree(tmp, ignore_errors=True)
print("ok")
