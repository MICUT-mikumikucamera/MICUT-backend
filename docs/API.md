# MiCut BE 앱 연결 API 명세 v0.1

2026-11-04 기준 · v0 대비 바뀐 점은 [6. 변경 이력](#6-변경-이력)에 있어요.

## 1. 백엔드 스택과 명세 공유 방식

백엔드는 **Python + FastAPI**로 개발하고, Flutter와는 **HTTP + JSON**으로만 주고받아요.

| 시점 | 명세 보는 곳 |
| --- | --- |
| 지금 | 이 파일 + `contracts/examples/` (응답 예시 JSON, 가짜 데이터로 바로 사용 가능) |
| 서버 주소 공유 전 | `openapi.json` 파일 공유 → editor.swagger.io에 붙여 넣으면 Swagger 화면으로 확인 |
| 서버가 올라간 뒤 | `서버주소/docs`의 Swagger가 최종 기준. 거기서 API를 직접 호출해 볼 수 있음 |

**공유 서버 주소: `https://micut-backend.onrender.com`** (Swagger: `https://micut-backend.onrender.com/docs`)

- 무료 서버라 15분 동안 요청이 없으면 잠들어요. 잠든 뒤 첫 요청은 약 1분 걸리니, 앱에서는 첫 요청의 타임아웃을 넉넉히(60초 이상) 잡아 주세요.
- 서버가 재시작되면 작업 기록과 이미지가 지워져요. 오래된 `job_id`로 조회하면 `404 JOB_NOT_FOUND`가 날 수 있어요.

서버 실행 방법은 저장소 `README.md`에 있어요.

## 2. 기본 흐름과 공통 규칙

앱은 사진을 보내 `job_id`를 받고, 그 번호로 상태를 반복 조회해 결과를 받아요.

1. 사진 전송 → `job_id` 받기
2. `job_id`로 1~2초마다 상태 조회 (폴링)
3. `done` → 결과 이미지 다운로드 / `failed` → 재시도 또는 다시 찍기

**공통**

- 응답은 모두 JSON (discard의 `204`만 본문 없음)
- `image_url`은 경로만 줘요 → 앱에서 서버 주소를 앞에 붙여서 사용
- 시간은 한국 시간 ISO 형식 (`2026-11-05T14:00:00+09:00`). 소수점 초가 붙을 수 있어요.
- 로그인 없음
- `job_id`는 랜덤 값이에요 (예: `j_20261105_a1b2c3d4e5f6`). 형식에 의존하지 말고 문자열 그대로 쓰시면 돼요.

**AI 연결 전 시연 모드 (현재)**

AI가 붙기 전까지는 서버가 AI 대신 가짜 처리를 해요. 접수하면 약 2초 뒤 `processing`, 약 5초 뒤 `done`이 되고, 결과 이미지는 원본 사진을 복사한 것이에요. 가짜 처리는 실패하지 않으므로 `failed` 화면은 `contracts/examples/job_failed.json`으로 만들어 주세요.

## 3. API

### ① 사진 접수

`POST /api/v1/jobs` · `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| photo | 파일 | O | 촬영한 사진 원본 (JPEG 또는 PNG, 10MB 이하) |
| w | int | O | 사진 가로 픽셀 |
| h | int | O | 사진 세로 픽셀 |
| rotation | int | O | 회전 각도 (예: 90) |
| fx | float | X | 카메라 초점거리, 모르면 안 보내도 됨 |

- `w`, `h`, `rotation`, `fx`는 **각각 별도 폼 필드**로 보내 주세요. `capture` JSON 한 필드로 보내면 `422 INVALID_REQUEST`가 나요.
- 사진 형식은 파일 확장자가 아니라 파일 내용으로 확인해요. HEIC는 받지 않으니 JPEG로 보내 주세요.
- AI가 사진 EXIF의 초점거리를 쓰므로, 앱에서 다시 압축하거나 리사이즈하지 말고 원본 그대로 보내 주세요.

응답 `201`

```json
{
  "job_id": "j_20261105_a1b2c3d4e5f6",
  "photo": "/uploads/j_20261105_a1b2c3d4e5f6.jpg",
  "capture": { "w": 3024, "h": 4032, "rotation": 90, "fx": null },
  "status": "pending",
  "attempt": 1,
  "result": null,
  "error": null,
  "created_at": "2026-11-05T14:00:00+09:00",
  "updated_at": "2026-11-05T14:00:00+09:00"
}
```

실패: `400 UPLOAD_INVALID_FORMAT`, `413 UPLOAD_TOO_LARGE`, `422 INVALID_REQUEST`. 업로드가 실패하면 작업이 만들어지지 않아요.

### ② 상태 조회

`GET /api/v1/jobs/{job_id}`

응답 모양은 ①과 같아요. AI가 실패해도 조회 자체는 성공이라 `200`이고, 성공·실패는 `status`로 판단해 주세요.

| status | 화면 | 채워지는 필드 |
| --- | --- | --- |
| pending | 처리 중 | - |
| processing | 처리 중 | - |
| done | 결과 화면 | result |
| failed | 실패 안내 | error |

done일 때

```json
"result": { "image_url": "/results/j_20261105_a1b2c3d4e5f6.jpg", "tags": ["outdoor", "day"], "card_ids": [] }
```

- `tags`: AI가 분류한 장면 태그 (목록은 아직 미정, 시연 모드에서는 빈 배열)
- `card_ids`: 획득한 카드 (v0에서는 빈 배열)

failed일 때

```json
"error": { "code": "AI_TIMEOUT", "message": "처리가 오래 걸렸어요", "retryable": true }
```

실패: `404 JOB_NOT_FOUND`

### ③ 재시도

`POST /api/v1/jobs/{job_id}/retry` · 바디 없음

- `failed`이면서 `retryable: true`인 작업만 가능해요.
- 응답 `200`: 다시 `pending`이 된 작업 (①과 같은 모양). `attempt`가 +1 되고 `error`는 `null`이 돼요. 이후 다시 상태 조회하면 돼요.

실패: `404 JOB_NOT_FOUND`, `409 RETRY_NOT_ALLOWED` (실패 상태가 아니거나, 재시도할 수 없는 실패)

### ④ 재시도 안 함

`POST /api/v1/jobs/{job_id}/discard` · 바디 없음

- 실패 화면에서 사용자가 재시도 대신 **다시 찍기 / 닫기**를 누르면 호출해 주세요.
- 응답 `204` (본문 없음)
- 호출하면 그 작업의 `error.retryable`이 `false`로 바뀌고, 이후 재시도할 수 없어요.
- 재시도 가능한 실패가 아닌 작업에 호출해도 아무것도 바뀌지 않고 `204`예요.

실패: `404 JOB_NOT_FOUND`

### ⑤ 결과 이미지

`GET {서버주소}{image_url}` → 이미지 파일

### ⑥ 서버 확인

`GET /health` → `{"status": "ok"}`

## 4. 에러 처리와 사진 보관

실패는 항상 같은 모양이고, 화면은 `retryable`로 나눠요 (`true` 재시도 버튼, `false` 다시 찍기 안내). `message`는 사용자에게 그대로 보여 줘도 돼요.

```json
{ "status": "failed", "error": { "code": "UPLOAD_TOO_LARGE", "message": "사진 용량이 너무 커요", "retryable": false } }
```

- **요청 자체가 실패**하면 아래 HTTP 상태 코드와 함께 이 모양이 본문으로 와요.
- **AI 처리 실패**는 조회 응답(`200`)의 `error`로 와요.

| code | 상황 | HTTP | retryable | 화면 |
| --- | --- | --- | --- | --- |
| UPLOAD_INVALID_FORMAT | 지원하지 않는 사진 형식 | 400 | false | 다시 찍기 |
| UPLOAD_TOO_LARGE | 용량 초과 (10MB) | 413 | false | 다시 찍기 |
| INVALID_REQUEST | 필수 필드 누락, 타입 오류 | 422 | false | 다시 찍기 |
| JOB_NOT_FOUND | 없는 작업 | 404 | false | 다시 찍기 |
| RETRY_NOT_ALLOWED | 재시도할 수 없는 작업에 재시도 | 409 | false | 다시 찍기 |
| PERSON_NOT_FOUND | 사람 인식 실패 | 조회 200 | false | 다시 찍기 |
| FOOT_LOW_CONFIDENCE | 발이 잘 안 보임 | 조회 200 | false | 다시 찍기 |
| AI_TIMEOUT | 처리 시간 초과 | 조회 200 | true | 재시도 |
| RENDER_FAILED | 렌더링 실패 | 조회 200 | true | 재시도 |
| INTERNAL_ERROR | 기타 서버 오류 | 500 | true | 재시도 |

코드 목록의 원본은 `contracts/error_codes.json`이고, 서버는 이 파일의 문구를 그대로 응답해요.

**사진 보관**

- 원본 사진은 합성이 끝나거나, 재시도하지 않기로 하면 서버에서 삭제돼요. 그래서 응답의 `photo`는 앱에서 쓰지 말아 주세요.
- 재시도 가능한 실패를 discard 없이 그냥 두면, 24시간 뒤 서버가 자동으로 discard 처리해요. 그 뒤에는 재시도할 수 없어요.
- 결과 이미지는 서버에 남아 있어서 `image_url`로 다시 받을 수 있어요. 단, 지금 공유 서버(Render 무료)는 재시작하면 이미지가 지워지므로, 앱은 `done`을 받으면 결과 이미지를 바로 내려받아 기기에 저장해 주세요.

## 5. FE 확인 요청과 확정 전 항목

**FE에 확인 부탁드릴 것**

- [ ] 접수할 때 `w`, `h`, `rotation`, `fx`를 각각 폼 필드로 보내 주실 수 있는지 (현재 `ApiJobRepository`는 `capture` JSON 한 필드로 보내고 있어요)
- [ ] `w`, `h`를 파일에 저장된 그대로의 크기(회전 적용 전 기준)로 보내 주실 수 있는지
- [ ] 사진을 재압축·리사이즈 없이 원본으로 보내 주실 수 있는지 (HEIC는 JPEG로)
- [ ] 폴링 간격 1~2초 괜찮은지
- [ ] 에러별 화면이 "재시도 / 다시 찍기" 두 가지로 충분한지
- [ ] 실패 화면에서 다시 찍기 / 닫기를 누를 때 discard 호출이 가능한지

**아직 확정 전**

- `PERSON_NOT_FOUND` / `FOOT_LOW_CONFIDENCE`가 "사람 없는 장소" 디자인과 맞는지 (AI 파트와 확인 중)
- `AI_TIMEOUT` 기준 시간
- `tags` 목록, `card_ids`를 채우는 조건

## 6. 변경 이력

**v0.1 (2026-11-04)**

- 에러 코드 3개 추가: `INVALID_REQUEST`, `JOB_NOT_FOUND`, `RETRY_NOT_ALLOWED`
- 요청 실패의 HTTP 상태 코드 확정 (400 / 404 / 409 / 413 / 422 / 500)
- 업로드 기준 확정: JPEG·PNG, 10MB 이하, 원본 그대로
- 재시도 응답 `200` + 작업, 각 API의 실패 응답 명시
- AI 연결 전 시연 모드 추가: 서버가 가짜 처리로 `done`까지 진행
- 공유 서버 주소 추가: `https://micut-backend.onrender.com` (2026-11-05)
