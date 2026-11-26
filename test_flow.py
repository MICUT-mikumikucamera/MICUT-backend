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
from schemas import Job, JobError, People, Person  # noqa: E402

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
piped = []  # 합성에 넘긴 사람 (Person)


def stub_pipeline(photo, out, person):
    assert photo.read_bytes() == JPG
    piped.append(person)
    image = out / "composite" / "composite_depth.png"
    image.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "samples" / "cafe-composite.png", image)


fake_ai.run_pipeline = stub_pipeline
# 인물 선택 전의 흐름 테스트는 사람이 없는 사진으로 한다 (선택 없이 바로 done). 인물 선택은 아래에서 따로.
fake_people = fake_ai.detect_people
fake_ai.detect_people = lambda photo: People(status="no_person", people=[])


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

# 컬렉션: done이 되면 AI가 정한 card_id를 X-Device-Id를 보낸 기기의 컬렉션에 기록한다
DEV = {"X-Device-Id": "dev-a"}


def submit_as(headers, card_id):
    fake_ai.read_card_id = lambda out: card_id
    r = c.post("/api/v1/jobs", files={"photo": ("a.jpg", JPG, "image/jpeg")}, data=FIELDS, headers=headers)
    assert r.status_code == 201, r.text
    assert "device_id" not in r.json()                      # 기기 ID는 응답에 안 나간다
    job = c.get(f"/api/v1/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done"
    return job["job_id"], job["result"]["card_ids"], job["result"]["new_card_ids"]


empty = c.get("/api/v1/collection", headers=DEV).json()
assert empty["total"] == 12 and empty["acquired_count"] == 0
assert [card["no"] for card in empty["cards"]] == list(range(1, 13))

v1, cards, new = submit_as(DEV, "v_sign")
assert cards == ["v_sign"] and new == ["v_sign"]                        # 처음 얻은 카드는 신규
v2, cards, new = submit_as(DEV, "v_sign")
assert cards == ["v_sign"] and new == []                                # 같은 카드는 신규 아님
k1, cards, new = submit_as(DEV, "kiss")
assert cards == ["kiss"] and new == ["kiss"]
assert submit_as(DEV, None)[1:] == ([], [])                             # 컬렉션에 없는 포즈 → 카드 없음
assert submit_as(DEV, "COL_V")[1:] == ([], [])                          # cards.json에 없는 id도 카드 없음
col = c.get("/api/v1/collection", headers=DEV).json()
assert col["acquired_count"] == 2
photos = {card["id"]: [ph["job_id"] for ph in card["photos"]] for card in col["cards"]}
assert photos["v_sign"] == [v1, v2] and photos["kiss"] == [k1]          # 사진은 얻은 순서로 쌓인다
assert sum(map(len, photos.values())) == 3

# 다른 기기와는 섞이지 않고, 헤더 없이 찍으면 card_ids는 오지만 기록되지 않는다
assert c.get("/api/v1/collection", headers={"X-Device-Id": "dev-b"}).json()["acquired_count"] == 0
assert submit_as({}, "leek")[1:] == (["leek"], [])

# 기기 ID가 없거나 형식이 틀리면 422
assert c.get("/api/v1/collection").json()["error"]["code"] == "INVALID_REQUEST"
for bad in ["", "a b", "x" * 65, "a/b"]:
    assert c.get("/api/v1/collection", headers={"X-Device-Id": bad}).status_code == 422, bad
r = c.post("/api/v1/jobs", files={"photo": ("a.jpg", JPG, "image/jpeg")}, data=FIELDS, headers={"X-Device-Id": "a b"})
assert r.status_code == 422

# 로그인: 구글 검증 대신 가짜 토큰 → sub
from routers import auth  # noqa: E402

real_verify = auth.verify_google
try:
    real_verify("x")  # GOOGLE_CLIENT_ID 없이는 아예 검증하지 않는다
    raise AssertionError
except RuntimeError:
    pass
GOOGLE = {"tok-a": "111", "tok-b": "222"}


def fake_verify(token):
    if token not in GOOGLE:
        raise ValueError("bad token")
    return GOOGLE[token]


auth.verify_google = fake_verify


def login(token, headers=None):
    return c.post("/api/v1/auth/google", json={"id_token": token}, headers=headers or {})


def unauthorized(r):
    return r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


assert unauthorized(login("forged"))
assert unauthorized(c.get("/api/v1/me"))
assert unauthorized(c.get("/api/v1/me", headers={"Authorization": "Bearer nope"}))

# 첫 로그인: 온보딩 필요. 이 기기(dev-a)로 모은 카드가 계정으로 옮겨진다.
r = login("tok-a", DEV)
assert r.status_code == 200 and r.json()["needs_onboarding"] is True and r.json()["nickname"] is None
A = {"Authorization": f"Bearer {r.json()['token']}"}
assert c.get("/api/v1/collection", headers=A).json()["acquired_count"] == 2
assert c.get("/api/v1/collection", headers=DEV).json()["acquired_count"] == 0
assert c.get("/api/v1/me", headers=A).json() == {"needs_onboarding": True, "nickname": None}


def onboard(nickname, headers=A, terms=True, privacy=True):
    body = {"nickname": nickname, "terms_accepted": terms, "privacy_accepted": privacy}
    return c.post("/api/v1/me/onboarding", json=body, headers=headers)


def error_code(r):
    return r.status_code, r.json()["error"]["code"]


# 규칙 위반·필수 동의 누락은 422, 예약어는 409. 실패하면 아무것도 저장되지 않는다.
for bad in ["a", "x" * 21, "미 쿠", "미쿠​짱", "미쿠😀", "미쿠©"]:
    assert error_code(onboard(bad)) == (422, "INVALID_REQUEST"), bad
assert error_code(onboard("미쿠짱", terms=False)) == (422, "INVALID_REQUEST")
assert error_code(onboard("미쿠짱", privacy=False)) == (422, "INVALID_REQUEST")
assert error_code(onboard("ADMIN")) == (409, "NICKNAME_TAKEN")
assert c.get("/api/v1/me", headers=A).json()["needs_onboarding"] is True
assert unauthorized(onboard("미쿠짱", headers={}))

assert onboard("가나").json() == {"needs_onboarding": False, "nickname": "가나"}  # 풀어 쓴 한글도 2글자
assert onboard("가" * 20).status_code == 200
r = onboard("Miku")                                                     # 다시 부르면 닉네임만 바뀐다
assert r.json() == {"needs_onboarding": False, "nickname": "Miku"}
assert onboard("Miku").status_code == 200                               # 내 닉네임은 중복이 아니다

# 다른 계정은 같은 닉네임(대소문자만 달라도)을 못 쓴다
B = {"Authorization": f"Bearer {login('tok-b').json()['token']}"}
assert error_code(onboard("MIKU", B)) == (409, "NICKNAME_TAKEN")
assert c.get("/api/v1/me", headers=B).json() == {"needs_onboarding": True, "nickname": None}

again = login("tok-a").json()                                           # 다시 로그인하면 바로 홈
assert again["needs_onboarding"] is False and again["nickname"] == "Miku"

# 로그인한 채 찍은 사진의 카드는 계정 컬렉션에 쌓인다 (기기 ID를 같이 보내도 계정 우선)
assert submit_as({**A, **DEV}, "leek")[1:] == (["leek"], ["leek"])
assert c.get("/api/v1/collection", headers=A).json()["acquired_count"] == 3
assert c.get("/api/v1/collection", headers=B).json()["acquired_count"] == 0
assert unauthorized(c.get("/api/v1/collection", headers={**DEV, "Authorization": "Bearer nope"}))

# 로그아웃하면 그 토큰은 끝. 만료된 세션도 401.
assert c.post("/api/v1/auth/logout", headers=B).status_code == 204
assert unauthorized(c.get("/api/v1/me", headers=B))
store.run("UPDATE sessions SET expires_at = ?", ("2000-01-01T00:00:00+09:00",))
assert unauthorized(c.get("/api/v1/me", headers=A))

# 사람이 없으면 선택 없이 solo로 합성된다
job = c.get(f"/api/v1/jobs/{submit()}").json()
assert job["status"] == "done" and job["person"] == {"mode": "solo", "person_id": None}
assert job["people"]["people"] == [] and piped[-1] == Person(mode="solo")

# 사람이 있으면 awaiting_person에서 멈추고 people을 보여 준다. 원본은 남아 있다.
fake_ai.detect_people = fake_people
jid = submit()
job = c.get(f"/api/v1/jobs/{jid}").json()
assert job["status"] == "awaiting_person" and job["person"] is None and job["result"] is None
assert job["people"]["recommended_person_id"] == "p0"
assert [(p["person_id"], p["eligible"]) for p in job["people"]["people"]] == [("p0", True), ("p1", False)]
assert job["people"]["people"][1]["reason"] == "too_small"
assert photo_exists(jid)


def select(job_id, body):
    return c.post(f"/api/v1/jobs/{job_id}/person", json=body)


# 잘못된 선택은 422, 작업은 그대로 기다린다
for bad in [{"mode": "human", "person_id": "p1"},       # eligible false
            {"mode": "human", "person_id": "p9"},       # 없는 사람
            {"mode": "human", "person_id": None},
            {"mode": "solo", "person_id": "p0"},
            {"mode": "copy", "person_id": "p0"},
            {}]:
    r = select(jid, bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", (bad, r.text)
assert c.get(f"/api/v1/jobs/{jid}").json()["status"] == "awaiting_person"
assert c.post(f"/api/v1/jobs/{jid}/retry").status_code == 409            # 선택 대기는 재시도 대상 아님

# 고르면 processing으로 돌려주고, 그 사람으로 합성해 done
r = select(jid, {"mode": "human", "person_id": "p0"})
assert r.status_code == 200, r.text
assert r.json()["status"] == "processing" and r.json()["person"] == {"mode": "human", "person_id": "p0"}
assert "device_id" not in r.json()
job = c.get(f"/api/v1/jobs/{jid}").json()
assert job["status"] == "done" and piped[-1] == Person(mode="human", person_id="p0")

# 이미 고른 작업, 없는 작업
r = select(jid, {"mode": "human", "person_id": "p0"})
assert r.status_code == 409 and r.json()["error"]["code"] == "PERSON_SELECT_NOT_ALLOWED"
assert select("nope", {"mode": "solo", "person_id": None}).status_code == 404

# 따라 하지 않기
jid = submit()
assert select(jid, {"mode": "solo", "person_id": None}).status_code == 200
assert c.get(f"/api/v1/jobs/{jid}").json()["status"] == "done" and piped[-1] == Person(mode="solo")

# 합성 실패 뒤 재시도: 사람 인식·선택 없이 처음 고른 사람으로 다시 합성
jid = submit()
select(jid, {"mode": "human", "person_id": "p0"})
make_failed(jid)
fake_ai.detect_people = lambda photo: (_ for _ in ()).throw(AssertionError("인식을 다시 하면 안 됨"))
assert c.post(f"/api/v1/jobs/{jid}/retry").status_code == 200
job = c.get(f"/api/v1/jobs/{jid}").json()
assert job["status"] == "done" and job["person"]["person_id"] == "p0" and piped[-1].person_id == "p0"

store.conn.close()
os.chdir(ROOT)
shutil.rmtree(tmp, ignore_errors=True)
print("ok")
