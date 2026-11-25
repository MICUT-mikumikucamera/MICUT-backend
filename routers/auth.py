import hashlib
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

import store
from errors import AppError
from schemas import DEVICE_ID, GoogleLogin, Login, Me, NicknameBody, NicknameCheck, NicknameIssue

router = APIRouter(prefix="/api/v1", tags=["auth"])

KST = timezone(timedelta(hours=9))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")  # Google Cloud의 Web 클라이언트 ID (앱의 serverClientId)
# ponytail: 세션은 로그인 후 90일 고정. 쓰는 동안 연장하려면 조회 때 expires_at 갱신
SESSION_DAYS = 90
NICKNAME_MIN, NICKNAME_MAX = 2, 20
RESERVED = {"관리자", "운영자", "admin", "micut", "미컷", "미쿠"}
# 앱(nickname_validator.dart)과 같은 범위
EMOJI = re.compile("[\U0001F000-\U0001FAFF←-⇿⌀-⏿☀-➿⬀-⯿️‍⃣]")

bearer = HTTPBearer(auto_error=False)  # Swagger에 Authorize 버튼이 생긴다.
Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
DeviceId = Annotated[str | None, Header(pattern=DEVICE_ID)]


def verify_google(token: str) -> str:
    """구글 ID token의 서명·만료·대상 앱을 확인하고 계정 고유 번호(sub)를 돌려준다. 통과 못 하면 ValueError."""
    if not GOOGLE_CLIENT_ID:  # 대상 앱 없이 검증하면 다른 앱용 토큰도 통과한다.
        raise RuntimeError("GOOGLE_CLIENT_ID 환경 변수가 없다")
    return id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID)["sub"]


def hashed(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def optional_user(cred: Bearer) -> str | None:
    """Authorization 헤더가 없으면 None. 있는데 틀리거나 만료됐으면 401."""
    if cred is None:
        return None
    rows = store.run("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (hashed(cred.credentials),))
    if not rows:
        raise AppError("UNAUTHORIZED")
    user_id, expires_at = rows[0]
    if datetime.fromisoformat(expires_at) < datetime.now(KST):
        store.run("DELETE FROM sessions WHERE token_hash = ?", (hashed(cred.credentials),))
        raise AppError("UNAUTHORIZED")
    return user_id


def current_user(user_id: Annotated[str | None, Depends(optional_user)]) -> str:
    if user_id is None:
        raise AppError("UNAUTHORIZED")
    return user_id


User = Annotated[str, Depends(current_user)]


def owner(user_id: Annotated[str | None, Depends(optional_user)], x_device_id: DeviceId = None) -> str | None:
    """컬렉션 주인. 로그인했으면 계정, 아니면 기기 ID. 계정 id에는 ':'가 있어 기기 ID와 겹치지 않는다."""
    return user_id or x_device_id


def me(user_id: str) -> Me:
    nickname, terms_agreed_at = store.run("SELECT nickname, terms_agreed_at FROM users WHERE user_id = ?", (user_id,))[0]
    status = "needs_nickname" if nickname is None else "needs_terms" if terms_agreed_at is None else "signed_in"
    return Me(status=status, nickname=nickname)


# ponytail: 길이는 NFC 정규화 후 코드 포인트 수로 센다. 결합 문자가 섞이면 앱(글자 수)과 다를 수 있음
def nickname_issue(nickname: str, user_id: str) -> NicknameIssue | None:
    if re.search(r"\s", nickname):
        return "has_whitespace"
    if EMOJI.search(nickname):
        return "has_emoji"
    if len(nickname) < NICKNAME_MIN:
        return "too_short"
    if len(nickname) > NICKNAME_MAX:
        return "too_long"
    key = nickname.casefold()
    if key in RESERVED or store.run("SELECT 1 FROM users WHERE nickname_key = ? AND user_id <> ?", (key, user_id)):
        return "taken"
    return None


@router.post("/auth/google", response_model=Login)
def login_google(body: GoogleLogin, x_device_id: DeviceId = None):
    try:
        user_id = f"google:{verify_google(body.id_token)}"
    except ValueError:
        raise AppError("UNAUTHORIZED")
    now = datetime.now(KST)
    store.run("INSERT INTO users (user_id, created_at) VALUES (?, ?) ON CONFLICT (user_id) DO NOTHING",
              (user_id, now.isoformat()))
    if x_device_id:  # 로그인 전에 이 기기로 모은 카드를 계정으로 옮긴다.
        store.run("UPDATE acquisitions SET device_id = ? WHERE device_id = ?", (user_id, x_device_id))
    token = secrets.token_urlsafe(32)
    store.run("INSERT INTO sessions VALUES (?, ?, ?)",
              (hashed(token), user_id, (now + timedelta(days=SESSION_DAYS)).isoformat()))
    return Login(token=token, **me(user_id).model_dump())


@router.post("/auth/logout", status_code=204)
def logout(cred: Bearer):
    if cred:
        store.run("DELETE FROM sessions WHERE token_hash = ?", (hashed(cred.credentials),))


@router.get("/me", response_model=Me)
def read_me(user_id: User):
    return me(user_id)


@router.get("/nicknames/check", response_model=NicknameCheck)
def check_nickname(nickname: str, user_id: User):
    issue = nickname_issue(unicodedata.normalize("NFC", nickname), user_id)
    return NicknameCheck(available=issue is None, issue=issue)


@router.put("/me/nickname", response_model=Me)
def save_nickname(body: NicknameBody, user_id: User):
    nickname = unicodedata.normalize("NFC", body.nickname)
    issue = nickname_issue(nickname, user_id)
    if issue == "taken":
        raise AppError("NICKNAME_TAKEN")
    if issue:
        raise AppError("INVALID_REQUEST")
    try:
        store.run("UPDATE users SET nickname = ?, nickname_key = ? WHERE user_id = ?",
                  (nickname, nickname.casefold(), user_id))
    except store.Conflict:  # 확인과 저장 사이에 다른 사람이 먼저 가져간 경우
        raise AppError("NICKNAME_TAKEN")
    return me(user_id)


@router.post("/me/terms", response_model=Me)
def agree_terms(user_id: User):
    store.run("UPDATE users SET terms_agreed_at = ? WHERE user_id = ? AND terms_agreed_at IS NULL",
              (datetime.now(KST).isoformat(), user_id))
    return me(user_id)
