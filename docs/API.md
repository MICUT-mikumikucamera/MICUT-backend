# MiCut BE 앱 연결 API 명세 v0.3

2026-11-13 기준 · v0 대비 바뀐 점은 [6. 변경 이력](#6-변경-이력)에 있어요.

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
- CORS는 모든 출처를 허용해요. Flutter 웹(브라우저)에서도 바로 호출할 수 있어요.
- `image_url`은 경로만 줘요 → 앱에서 서버 주소를 앞에 붙여서 사용
- 시간은 한국 시간 ISO 형식 (`2026-11-05T14:00:00+09:00`). 소수점 초가 붙을 수 있어요.
- 로그인 없음. 대신 **기기 ID**로 사용자를 구분해요 (아래)
- `job_id`는 랜덤 값이에요 (예: `j_20261105_a1b2c3d4e5f6`). 형식에 의존하지 말고 문자열 그대로 쓰시면 돼요.

**기기 ID (`X-Device-Id` 헤더)**

컬렉션은 기기별로 쌓여요. 앱을 처음 실행할 때 UUID를 하나 만들어 기기에 저장하고, 사진 접수(①)와 컬렉션 조회(⑦)에 `X-Device-Id` 헤더로 보내 주세요.

- 형식: 1~64자, 영문·숫자·`-`·`_` (예: `3f2b8c1e-5d4a-4e7b-9c0d-1a2b3c4d5e6f`)
- 앱을 지우면 새 ID가 만들어지므로 컬렉션도 처음부터 시작해요.

**AI 연결 전 시연 모드 (현재)**

AI가 붙기 전까지는 서버가 AI 대신 가짜 처리를 해요. 접수하면 약 2초 뒤 `processing`, 약 5초 뒤 `done`이 되고, 결과 이미지는 원본 사진을 복사한 것이에요. 가짜 처리는 실패하지 않으므로 `failed` 화면은 `contracts/examples/job_failed.json`으로 만들어 주세요.

## 3. API

### ① 사진 접수

`POST /api/v1/jobs` · `multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| photo | 파일 | O | 크롭·축소하지 않은 전체 화각 사진 (JPEG 또는 PNG, 10MB 이하) |
| w | int | O | 보낸 사진의 실제 가로 픽셀 |
| h | int | O | 보낸 사진의 실제 세로 픽셀 |
| rotation | int | O | 항상 `0` (앱이 EXIF 방향을 픽셀에 적용한 뒤 보냄) |
| fx | float | X | 카메라 초점거리, 모르면 안 보내도 됨 |
| crop | JSON 텍스트 | O | 최종 결과로 쓸 영역 `{"x":875,"y":0,"width":2250,"height":3000}` |

헤더 `X-Device-Id` (선택): 보내면 이 사진으로 얻은 카드가 그 기기의 컬렉션에 기록돼요. 안 보내면 `card_ids`는 채워지지만 컬렉션에는 기록되지 않아요. 형식이 맞지 않으면 `422 INVALID_REQUEST`예요.

- `w`, `h`, `rotation`, `fx`, `crop`은 **각각 별도 폼 필드**로 보내 주세요. `capture` JSON 한 필드로 보내면 `422 INVALID_REQUEST`가 나요.
- `crop`은 multipart의 텍스트 필드예요. 값은 위 JSON 그대로이고, 문자열로 한 번 더 감싸지(이중 인코딩) 않아요.
- `crop` 좌표는 보낸 사진의 좌상단이 `(0, 0)`인 **정수 픽셀**이에요. 사용하는 영역은 `[x, x+width)`, `[y, y+height)`예요.
- 서버는 사진을 회전하지 않아요. 방향 정리가 끝난 사진과 그 크기를 보내 주세요.
- 사진 형식은 파일 확장자가 아니라 파일 내용으로 확인해요. HEIC는 받지 않으니 JPEG로 보내 주세요.
- AI가 사진 EXIF의 초점거리를 써요. JPEG로 다시 인코딩할 때 EXIF(특히 초점거리)가 남아 있어야 해요.

**검증** — 아래 중 하나라도 맞지 않으면 자동 보정 없이 `422 INVALID_REQUEST`예요.

- 사진의 실제 크기 == `w`, `h`
- `rotation == 0`
- `crop`이 JSON 객체이고 네 값이 모두 정수 (`875.0`, `"875"`도 거절)
- `x >= 0`, `y >= 0`, `width > 0`, `height > 0`, `x + width <= w`, `y + height <= h`

응답 `201`

```json
{
  "job_id": "j_20261105_a1b2c3d4e5f6",
  "photo": "/uploads/j_20261105_a1b2c3d4e5f6.jpg",
  "capture": {
    "w": 4000, "h": 3000, "rotation": 0, "fx": null,
    "crop": { "x": 875, "y": 0, "width": 2250, "height": 3000 }
  },
  "status": "pending",
  "attempt": 1,
  "result": null,
  "error": null,
  "created_at": "2026-11-05T14:00:00+09:00",
  "updated_at": "2026-11-05T14:00:00+09:00"
}
```

실패: `400 UPLOAD_INVALID_FORMAT` (지원하지 않거나 깨진 사진), `413 UPLOAD_TOO_LARGE`, `422 INVALID_REQUEST`. 업로드가 실패하면 작업이 만들어지지 않아요.

- `capture.crop`은 조회 응답에도 그대로 남아요. 2026-11-08 이전에 만든 작업은 `crop`이 `null`이에요.
- 재시도할 때도 처음 보낸 원본과 `crop`을 그대로 써요.

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
"result": {
  "image_url": "/results/j_20261105_a1b2c3d4e5f6.jpg",
  "tags": [],
  "card_ids": ["v_sign"],
  "new_card_ids": ["v_sign"]
}
```

- `tags`: AI가 분류한 장면 태그 (목록은 아직 미정, 지금은 빈 배열)
- `card_ids`: 이 사진으로 얻은 카드 id. 지금은 항상 1장이에요. 카드는 서버가 정해요 (⑦ 참고).
- `new_card_ids`: `card_ids` 중 이 기기가 **처음** 얻은 카드. 비어 있지 않으면 "신규 컬렉션 획득!" 팝업을 띄워 주세요. 접수 때 `X-Device-Id`를 안 보냈으면 항상 빈 배열이에요.
- 2026-11-13 이전에 끝난 작업은 `card_ids`, `new_card_ids` 모두 빈 배열이에요.

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

### ⑦ 컬렉션 조회

`GET /api/v1/collection` · 헤더 `X-Device-Id` (필수)

카드 12장 전체와, 이 기기가 각 카드를 얻은 사진 목록을 한 번에 줘요. 컬렉션 화면(진행도·잠긴 카드)과 카드 상세 화면(사진 여러 장·날짜)을 이 응답 하나로 그릴 수 있어요.

응답 `200`

```json
{
  "acquired_count": 1,
  "total": 12,
  "cards": [
    {
      "id": "v_sign", "no": 2, "name": "브이",
      "photos": [ { "job_id": "j_20261114_a1b2c3d4e5f6", "acquired_at": "2026-11-14T15:00:00+09:00" } ]
    },
    { "id": "gyaru_peace", "no": 1, "name": "갸루 피스", "photos": [] }
  ]
}
```

- `cards`는 `no` 순서예요. 위 예시는 줄인 것이고 실제로는 12장이 다 와요.
- `no`는 화면의 `#001` 번호예요. `name`은 못 얻은 카드에도 오니, 잠긴 카드는 앱에서 `???`로 가려 주세요.
- `photos`가 비어 있으면 못 얻은 카드예요. `acquired_count`는 `photos`가 있는 카드 수예요.
- `photos`는 얻은 순서(오래된 것 먼저)예요. 사진 파일은 앱이 기기에 저장한 결과 이미지를 `job_id`로 찾아 써 주세요. 서버 응답에는 이미지 주소를 넣지 않아요.
- 메모는 서버에 저장하지 않아요. 사진처럼 기기에 저장해 주세요.

**카드 목록**

| no | id | name |
| --- | --- | --- |
| 1 | `gyaru_peace` | 갸루 피스 |
| 2 | `v_sign` | 브이 |
| 3 | `half_heart` | 반하트 |
| 4 | `full_heart` | 완전 하트 |
| 5 | `wave` | 손 인사 |
| 6 | `miku_arms` | 미쿠 양팔 |
| 7 | `kiss` | 뽀뽀 |
| 8 | `cheek_poke` | 볼콕 |
| 9 | `flower_pose` | 꽃받침 |
| 10 | `gdg_pose` | GDG 포즈 |
| 11 | `alien_fingers` | 손가락으로 외계인 따라하기 |
| 12 | `leek` | 대파 들기 |

**카드를 얻는 방식**

- 작업이 `done`이 되는 순간 서버가 카드를 정해서 `result.card_ids`에 넣고, 그 기기의 컬렉션에 자동으로 기록해요. 앱이 따로 획득 등록을 호출할 필요는 없어요.
- 같은 카드를 여러 번 얻으면 `photos`에 사진이 쌓여요. 진행도는 늘지 않아요.
- 지금은 서버가 카드를 **무작위로** 골라요. AI가 미쿠의 포즈를 알려 주게 되면 그 포즈의 카드로 바뀌고, 응답 모양은 그대로예요.

실패: `422 INVALID_REQUEST` (`X-Device-Id`가 없거나 형식이 맞지 않음)

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
| INVALID_REQUEST | 필수 필드 누락, 타입 오류, 크기·crop 범위 불일치 | 422 | false | 다시 찍기 |
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

- [x] 접수할 때 `w`, `h`, `rotation`, `fx`, `crop`을 각각 폼 필드로 보내기 (FE 2026-11-08 반영)
- [ ] 방향 정리 후 JPEG로 다시 인코딩할 때 EXIF 초점거리가 남는지, 안 남는다면 `fx`를 보내 주실 수 있는지 (없으면 실제 AI가 실패해요)
- [ ] 전체 원본이 10MB를 넘지 않는지
- [ ] 폴링 간격 1~2초 괜찮은지
- [ ] 에러별 화면이 "재시도 / 다시 찍기" 두 가지로 충분한지
- [ ] 실패 화면에서 다시 찍기 / 닫기를 누를 때 discard 호출이 가능한지
- [ ] 기기 ID를 만들어 저장하고, 사진 접수·컬렉션 조회에 `X-Device-Id` 헤더로 보내기
- [ ] 결과 화면에서 `new_card_ids`로 "신규 컬렉션 획득!" 팝업 띄우기
- [ ] 결과 이미지를 기기에 저장할 때 `job_id`도 같이 저장하기 (컬렉션 사진을 찾을 때 씀)

**아직 확정 전**

- `PERSON_NOT_FOUND` / `FOOT_LOW_CONFIDENCE`가 "사람 없는 장소" 디자인과 맞는지 (AI 파트와 확인 중)
- `AI_TIMEOUT` 기준 시간
- `tags` 목록
- AI가 미쿠의 포즈를 알려 주는 방식 (그 전까지 카드는 무작위)

## 6. 변경 이력

**v0.3 (2026-11-13)**

- 신규: ⑦ 컬렉션 조회 `GET /api/v1/collection`, 카드 12장 목록
- ① 사진 접수: `X-Device-Id` 헤더 추가 (선택). 형식이 틀리면 `422 INVALID_REQUEST`. 폼 필드와 응답은 그대로예요.
- ② 상태 조회: `done`이면 `result.card_ids`에 카드 1장이 들어가요 (전에는 항상 빈 배열). `result.new_card_ids` 필드 추가.
- ③ 재시도: 바뀐 점 없음. 재시도 끝에 `done`이 되면 그때 카드를 얻고, 접수 때 보낸 기기 ID로 기록돼요.
- ④ discard, ⑤ 결과 이미지, ⑥ 서버 확인: 바뀐 점 없음
- 헤더를 안 보내는 지금 앱도 그대로 동작해요. 컬렉션에 기록되지 않을 뿐이에요.

**v0.2 (2026-11-09)**

- 앱이 크롭된 사진 대신 전체 원본과 `crop` 좌표를 보내요 (FE 변경 요청 2026-11-08)
- 접수에 `crop` 필드 추가 (필수), 응답 `capture.crop` 추가
- `rotation`은 항상 `0`, `w`, `h`는 방향 정리 후 실제 크기
- 사진 크기·crop 범위 검증 추가 (실패 시 `422 INVALID_REQUEST`), 깨진 사진은 `400 UPLOAD_INVALID_FORMAT`
- 결과 이미지에 `crop`을 적용하는 것은 AI 처리 쪽에서 아직 남은 작업

**v0.1 (2026-11-04)**

- 에러 코드 3개 추가: `INVALID_REQUEST`, `JOB_NOT_FOUND`, `RETRY_NOT_ALLOWED`
- 요청 실패의 HTTP 상태 코드 확정 (400 / 404 / 409 / 413 / 422 / 500)
- 업로드 기준 확정: JPEG·PNG, 10MB 이하, 원본 그대로
- 재시도 응답 `200` + 작업, 각 API의 실패 응답 명시
- AI 연결 전 시연 모드 추가: 서버가 가짜 처리로 `done`까지 진행
- 공유 서버 주소 추가: `https://micut-backend.onrender.com` (2026-11-05)
- CORS 허용 추가 (2026-11-05)
