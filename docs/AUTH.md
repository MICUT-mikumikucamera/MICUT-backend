# MiCut 로그인 API (초안)

2026-11-25 기준 · **초안이에요.** FE `main`의 `AuthGateway`(`lib/features/auth/auth_providers.dart`)에 맞춰 썼고, 확정되면 `docs/API.md`에 합칠게요.

## 요약

| 구분 | API | 앱 쪽 |
| --- | --- | --- |
| 신규 | `POST /api/v1/auth/google` | `AuthGateway.signInWithGoogle()` |
| 신규 | `POST /api/v1/me/onboarding` | `AuthGateway.completeOnboarding()` |
| 신규 | `GET /api/v1/me` | 앱을 켤 때 저장된 토큰 확인 (세션 복원) |
| 신규 | `POST /api/v1/auth/logout` | 설정의 로그아웃 |
| 변경 | `POST /api/v1/jobs`, `GET /api/v1/collection` | 로그인했으면 `X-Device-Id` 대신 계정 기준으로 컬렉션을 쌓아요 |

`GET /me`와 로그아웃은 지금 `AuthGateway`에 없어요. 앱 재실행과 세션 만료 화면에 필요해서 넣었어요.

로그인하지 않은 지금 앱도 그대로 동작해요 (`X-Device-Id` 방식 유지).

## 1. 로그인 방식

구글 로그인 화면은 **앱이** 띄워요. 서버는 앱이 받아 온 결과(ID token)를 검증만 해요.

1. 앱이 `google_sign_in`으로 로그인하고 **ID token**을 받아요. 이때 `serverClientId`에 서버의 Web 클라이언트 ID를 넣어야 ID token이 나와요.
2. ID token을 `POST /api/v1/auth/google`로 보내면 서버가 **우리 토큰**(`token`)을 줘요.
3. 이후 로그인이 필요한 요청에는 `Authorization: Bearer <token>` 헤더를 붙여 주세요. 구글 ID token은 처음 한 번만 보내요.

- `token`은 기기에 안전하게 저장해 주세요 (예: `flutter_secure_storage`).
- `token`은 **90일** 뒤 만료돼요. 만료되거나 로그아웃한 토큰을 보내면 `401 UNAUTHORIZED`가 와요. 이때 세션 만료 화면을 보여 주고 다시 구글 로그인을 하면 돼요.

## 2. 공통 응답

로그인 관련 응답에는 모두 이 두 필드가 와요.

```json
{ "needs_onboarding": true, "nickname": null }
```

| 필드 | 설명 |
| --- | --- |
| `needs_onboarding` | `true`면 닉네임 → 약관 화면으로, `false`면 홈으로 |
| `nickname` | 온보딩 전이면 `null` |

## 3. API

### 구글 로그인 `POST /api/v1/auth/google`

요청 (JSON)

```json
{ "id_token": "eyJhbGciOiJSUzI1NiIs..." }
```

헤더 `X-Device-Id` (선택): 보내면 **로그인 전에 이 기기로 모은 카드가 계정으로 옮겨져요.** 처음 로그인할 때 꼭 같이 보내 주세요.

응답 `200`

```json
{ "needs_onboarding": true, "nickname": null, "token": "q1w2e3..." }
```

- 처음 로그인이면 `needs_onboarding: true`예요. 온보딩을 마친 계정이면 `false`예요.
- `signInWithGoogle()`의 반환값은 `needs_onboarding`을 그대로 쓰면 돼요.
- 실패: `401 UNAUTHORIZED` (가짜, 만료, 다른 앱용 ID token), `422 INVALID_REQUEST` (`id_token` 없음)

### 온보딩 완료 `POST /api/v1/me/onboarding`

헤더 `Authorization` (필수)

요청 (JSON)

```json
{ "nickname": "미쿠짱", "terms_accepted": true, "privacy_accepted": true }
```

응답 `200` `{ "needs_onboarding": false, "nickname": "미쿠짱" }`

- 닉네임 규칙은 앱의 `NicknameRules`와 같아요: 2~20자, 공백과 보이지 않는 문자 불가, 이모지 불가.
- 대소문자만 다른 닉네임은 같은 닉네임으로 봐요 (`Miku` = `miku`).
- 이용약관과 개인정보 동의 시각을 서버에 따로 기록해요.
- 다시 부르면 닉네임만 바뀌고 동의 시각은 처음 것이 남아요. 나중에 설정에서 닉네임을 바꿀 때도 쓸 수 있어요.

| 실패 | 언제 | 앱 동작 |
| --- | --- | --- |
| `409 NICKNAME_TAKEN` | 다른 사람이 쓰는 닉네임이거나 예약어(관리자, 운영자, admin, micut, 미컷, 미쿠) | 닉네임 화면으로 돌아가 중복 에러 표시 |
| `422 INVALID_REQUEST` | 닉네임 규칙 위반, 또는 동의 둘 중 하나라도 `false` | 앱에서 미리 막으므로 보통 오지 않아요 |
| `401 UNAUTHORIZED` | 토큰이 없거나 만료 | 세션 만료 화면 |

실패하면 아무것도 저장되지 않아요.

### 내 정보 `GET /api/v1/me`

헤더 `Authorization` (필수) · 응답 `200` `{ "needs_onboarding": false, "nickname": "미쿠짱" }`

앱을 켤 때 저장된 토큰이 있으면 불러 주세요. `401`이면 세션 만료, `needs_onboarding: true`면 온보딩 화면이에요.

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
- **선택 동의:** 마케팅 수신 같은 선택 항목이 생기면 요청에 필드를 추가할게요.
- **로그인 필수 여부:** 로그인하지 않고도 쓸 수 있는지(게스트)에 따라 `X-Device-Id`를 남길지 정해요.
