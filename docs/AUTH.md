# MiCut 로그인 API (초안)

2026-11-20 기준 · **초안이에요.** FE `feat/auth-onboarding`의 `AuthRepository`에 맞춰 썼고, 확정되면 `docs/API.md`에 합칠게요.

## 요약

| 구분 | API | 앱 쪽 (`AuthRepository`) |
| --- | --- | --- |
| 신규 | `POST /api/v1/auth/google` | `signInWithGoogle()` |
| 신규 | `GET /api/v1/me` | `restore()`, `nickname()` |
| 신규 | `GET /api/v1/nicknames/check` | `checkNickname()` |
| 신규 | `PUT /api/v1/me/nickname` | `saveNickname()` |
| 신규 | `POST /api/v1/me/terms` | `agreeTerms()` |
| 신규 | `POST /api/v1/auth/logout` | `signOut()` |
| 변경 | `POST /api/v1/jobs`, `GET /api/v1/collection` | 로그인했으면 `X-Device-Id` 대신 계정 기준으로 컬렉션을 쌓아요 |

로그인하지 않은 지금 앱도 그대로 동작해요 (`X-Device-Id` 방식 유지).

## 1. 로그인 방식

구글 로그인 화면은 **앱이** 띄워요. 서버는 앱이 받아 온 결과(ID token)를 검증만 해요.

1. 앱이 `google_sign_in`으로 로그인하고 **ID token**을 받아요. 이때 `serverClientId`에 서버의 Web 클라이언트 ID를 넣어야 ID token이 나와요.
2. ID token을 `POST /api/v1/auth/google`로 보내면 서버가 **우리 토큰**(`token`)을 줘요.
3. 이후 로그인이 필요한 요청에는 `Authorization: Bearer <token>` 헤더를 붙여 주세요. 구글 ID token은 처음 한 번만 보내요.

- `token`은 기기에 안전하게 저장해 주세요 (예: `flutter_secure_storage`). 앱을 켤 때 이 토큰으로 `GET /api/v1/me`를 부르면 `restore()`가 돼요.
- `token`은 **90일** 뒤 만료돼요. 만료되거나 로그아웃한 토큰을 보내면 `401 UNAUTHORIZED`가 와요. 이때 세션 만료 화면을 보여 주고 다시 구글 로그인을 하면 돼요.

## 2. 로그인 단계 `status`

로그인 관련 응답에는 모두 `status`와 `nickname`이 와요.

```json
{ "status": "needs_nickname", "nickname": null }
```

| `status` | 앱 `AuthStatus` | 다음 화면 |
| --- | --- | --- |
| `needs_nickname` | `needsNickname` | 00-1 닉네임 |
| `needs_terms` | `needsTerms` | 00-2 이용약관 |
| `signed_in` | `signedIn` | 홈 |

- `signedOut`은 앱에 `token`이 없는 상태라 서버가 주지 않아요.
- `sessionExpired`는 `401 UNAUTHORIZED`를 받았을 때예요.

## 3. API

### 구글 로그인 `POST /api/v1/auth/google`

요청 (JSON)

```json
{ "id_token": "eyJhbGciOiJSUzI1NiIs..." }
```

헤더 `X-Device-Id` (선택): 보내면 **로그인 전에 이 기기로 모은 카드가 계정으로 옮겨져요.** 처음 로그인할 때 꼭 같이 보내 주세요.

응답 `200`

```json
{ "status": "needs_nickname", "nickname": null, "token": "q1w2e3..." }
```

- 처음 로그인이면 `needs_nickname`이에요. 이미 가입한 계정이면 저장된 단계(보통 `signed_in`)가 와요.
- 실패: `401 UNAUTHORIZED` (가짜, 만료, 다른 앱용 ID token), `422 INVALID_REQUEST` (`id_token` 없음)

### 내 정보 `GET /api/v1/me`

헤더 `Authorization` (필수) · 응답 `200` `{ "status": "signed_in", "nickname": "미쿠짱" }`

실패: `401 UNAUTHORIZED`

### 닉네임 확인 `GET /api/v1/nicknames/check?nickname=미쿠짱`

헤더 `Authorization` (필수)

응답 `200`

```json
{ "available": false, "issue": "taken" }
```

| `issue` | 앱 `NicknameIssue` |
| --- | --- |
| `null` | 사용 가능 |
| `too_short` | `tooShort` (2자 미만) |
| `too_long` | `tooLong` (20자 초과) |
| `has_whitespace` | `hasWhitespace` |
| `has_emoji` | `hasEmoji` |
| `taken` | `taken` (다른 사람이 사용 중이거나 예약어) |

- 규칙은 앱의 `validateNickname`과 같아요. 서버도 같은 순서(공백 → 이모지 → 길이 → 중복)로 확인해요.
- 대소문자만 다른 닉네임은 같은 닉네임으로 봐요 (`Miku` = `miku`).
- 지금 내 닉네임은 `taken`이 아니에요.

### 닉네임 저장 `PUT /api/v1/me/nickname`

헤더 `Authorization` (필수) · 요청 `{ "nickname": "미쿠짱" }` · 응답 `200` `{ "status": "needs_terms", "nickname": "미쿠짱" }`

- 나중에 설정에서 닉네임을 바꿀 때도 같은 API를 써요.
- 실패: `409 NICKNAME_TAKEN` (확인 뒤 다른 사람이 먼저 가져감), `422 INVALID_REQUEST` (규칙 위반), `401 UNAUTHORIZED`

### 약관 동의 `POST /api/v1/me/terms`

헤더 `Authorization` (필수) · 본문 없음 · 응답 `200` `{ "status": "signed_in", "nickname": "미쿠짱" }`

동의한 시각을 서버에 기록해요. 여러 번 불러도 처음 시각이 남아요.

### 로그아웃 `POST /api/v1/auth/logout`

헤더 `Authorization` · 응답 `204` (본문 없음)

그 토큰만 끝나요. 이미 끝난 토큰이어도 `204`예요. 앱은 저장한 토큰과 구글 로그인 상태(`GoogleSignIn.signOut()`)를 같이 지워 주세요.

## 4. 컬렉션과 로그인

- 사진 접수와 컬렉션 조회에 `Authorization`을 붙이면 **계정 컬렉션**에 쌓이고 계정 컬렉션을 보여 줘요. `X-Device-Id`를 같이 보내도 계정이 우선이에요.
- `Authorization`이 없으면 지금처럼 `X-Device-Id` 기준이에요.
- `Authorization`이 틀리거나 만료됐으면 기기 ID로 넘어가지 않고 `401 UNAUTHORIZED`예요.
- 다른 기기에서 같은 계정으로 로그인하면 같은 컬렉션이 보여요. 다만 결과 이미지와 메모는 기기에만 저장되므로, 다른 기기에서는 `photos[].job_id`에 맞는 이미지가 없을 수 있어요.

## 5. 에러 코드 추가

| 코드 | HTTP | 메시지 | 앱 동작 |
| --- | --- | --- | --- |
| `UNAUTHORIZED` | 401 | 다시 로그인해 주세요 | 세션 만료 화면 → 구글 로그인 |
| `NICKNAME_TAKEN` | 409 | 이미 사용 중인 닉네임이에요 | 닉네임 화면에 중복 에러 표시 |

## 6. 아직 정하지 않은 것

- **회원 탈퇴:** 구글 플레이는 계정을 만들 수 있는 앱에 앱 안 계정 삭제 기능을 요구해요. 출시 전에 추가해야 해요.
- **약관 항목:** 필수/선택(마케팅 등) 항목이 나뉘면 동의 항목을 받도록 바꿀게요. 지금은 "전체 동의" 한 번이에요.
- **로그인 필수 여부:** 로그인하지 않고도 쓸 수 있는지(게스트)에 따라 `X-Device-Id`를 남길지 정해요.
