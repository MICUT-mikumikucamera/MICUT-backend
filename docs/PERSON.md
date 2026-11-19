# MiCut 인물 선택 API 변경 사항 (명세 v0.4)

2026-11-19 기준 · 인물 선택과 관련해 바뀐 내용만 모았어요. 전체 명세는 `docs/API.md`에 있어요.

## 요약

미쿠를 합성하기 전에 AI가 사진 속 사람을 찾고, 사용자가 미쿠가 따라 할 사람을 고르는 단계가 생겨요.

1. 사진 접수 → AI가 사람 인식
2. 사람이 1명 이상이면 작업이 `awaiting_person`에서 멈춤 → 앱이 사람 목록(`people`)을 보여 주고 사용자가 선택
3. 앱이 선택을 보냄 → AI가 그 사람을 따라 미쿠를 합성 → `done` / `failed`

사람이 0명이면 선택 없이 바로 합성해요 (`solo`).

| 구분 | API | 내용 |
| --- | --- | --- |
| 신규 | `POST /api/v1/jobs/{job_id}/person` | 인물 선택 |
| 변경 | 작업 응답 (접수·조회·재시도) | 상태 `awaiting_person` 추가, `people`·`person` 필드 추가 |
| 변경 | 에러 코드 | `PERSON_SELECT_NOT_ALLOWED` (409) 추가 |
| 변경 없음 | discard, 결과 이미지, 컬렉션, `/health` | |

## 1. 상태 흐름

```
pending → processing (사람 인식) → awaiting_person → processing (합성) → done / failed
                                 ↘ 사람 0명이면 awaiting_person 없이 바로 합성
```

| status | 화면 | 채워지는 필드 |
| --- | --- | --- |
| pending | 처리 중 | - |
| processing | 처리 중 | 인식이 끝났으면 `people` |
| **awaiting_person** | **인물 선택** | `people` |
| done | 결과 화면 | `people`, `person`, `result` |
| failed | 실패 안내 | `error` (단계에 따라 `people`, `person`) |

- `awaiting_person`을 받으면 폴링을 멈추고 인물 선택 화면을 보여 주세요. 선택을 보낸 뒤 다시 폴링하면 돼요.
- 사람이 1명이어도 `awaiting_person`이 돼요. 사용자가 "따라 하지 않기"를 고를 수 있어야 해서예요.

## 2. 작업 응답에 추가된 필드

접수(①)·조회(②)·재시도(③)·인물 선택(⑧) 응답 모두에 들어가요. 처음에는 둘 다 `null`이에요.

`awaiting_person`일 때 조회 응답

```json
{
  "job_id": "j_20261119_a1b2c3d4e5f6",
  "status": "awaiting_person",
  "people": {
    "status": "ok",
    "recommended_person_id": "p0",
    "people": [
      { "person_id": "p0", "bbox_norm": [0.10, 0.15, 0.45, 0.80], "eligible": true },
      { "person_id": "p1", "bbox_norm": [0.75, 0.20, 0.82, 0.30], "eligible": false, "reason": "too_small" }
    ]
  },
  "person": null,
  "result": null,
  "error": null
}
```

(`photo`, `capture`, `attempt`, 시간 필드는 기존과 같아서 생략했어요.)

**`people`** — AI의 사람 인식 결과를 그대로 전달해요. 인식 전에는 `null`.

| 필드 | 설명 |
| --- | --- |
| `status` | `ok` (사람 있음) / `no_person` (사람 없음) |
| `recommended_person_id` | AI가 추천하는 사람. 선택 화면에서 미리 골라 두면 돼요. 없으면 `null` |
| `people[].person_id` | 선택할 때 보낼 id (`p0`, `p1`, …) |
| `people[].bbox_norm` | 사람 위치 `[왼쪽, 위, 오른쪽, 아래]`. 보낸 사진(전체 원본) 크기 대비 0~1 |
| `people[].eligible` | `false`면 고를 수 없는 사람이에요 (회색 처리) |
| `people[].reason` | `eligible`이 `false`인 이유 (예: `too_small`) |

AI가 다른 필드를 더 보내면 그대로 같이 와요. 모르는 필드는 무시해 주세요.

**`person`** — 고른 결과. 선택 전에는 `null`.

```json
{ "mode": "human", "person_id": "p0" }
```

사람이 0명이라 바로 합성한 작업은 서버가 `{"mode": "solo", "person_id": null}`로 채워요.

## 3. 신규 — 인물 선택 `POST /api/v1/jobs/{job_id}/person`

`application/json`

| 선택 | 바디 |
| --- | --- |
| 이 사람 따라 하기 | `{"mode": "human", "person_id": "p0"}` |
| 따라 하지 않기 | `{"mode": "solo", "person_id": null}` |

- `awaiting_person`인 작업만 고를 수 있어요.
- `human`이면 `person_id`는 `people.people` 중 `eligible: true`인 사람이어야 해요.
- `solo`면 `person_id`는 `null`이에요.

응답 `200`: `status`가 `processing`이고 `person`이 채워진 작업 (①과 같은 모양). 이후 다시 상태 조회하면 돼요.

| 실패 | 상황 |
| --- | --- |
| `404 JOB_NOT_FOUND` | 없는 작업 |
| `409 PERSON_SELECT_NOT_ALLOWED` | `awaiting_person`이 아닌 작업 (이미 골랐거나, 처리 중이거나, 끝난 작업) |
| `422 INVALID_REQUEST` | `mode`가 `human`/`solo`가 아님, 없는 `person_id`, `eligible: false`인 사람, `solo`인데 `person_id`가 있음 |

## 4. 재시도와의 관계

- 합성 단계에서 실패한 뒤 재시도하면, **사람 인식과 선택은 다시 하지 않고** 처음 고른 사람으로 다시 합성해요. 다시 `awaiting_person`이 되지 않아요.
- 사람 인식 단계에서 실패한 작업은 재시도하면 인식부터 다시 해요.

## 5. 에러 코드 추가

| code | 상황 | HTTP | retryable | 화면 |
| --- | --- | --- | --- | --- |
| PERSON_SELECT_NOT_ALLOWED | 인물을 고를 수 없는 작업에 선택 | 409 | false | 다시 찍기 |

## 6. 지금 상태와 확정 전 항목

- **사람 인식 AI 연결 전:** 서버가 모든 사진에 위 예시와 같은 가짜 사람 목록(`p0` 선택 가능, `p1` 너무 작음)을 돌려줘요. 인물 선택 화면은 이걸로 만들어 주세요.
- 인물 선택 화면에서 고르지 않고 나간 작업을 언제 정리할지는 아직 정하지 않았어요.
