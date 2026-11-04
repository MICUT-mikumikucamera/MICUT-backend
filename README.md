# MICUT-backend

미컷 앱 연결 백엔드 (FastAPI). 사진 접수, 상태 조회, 재시도, discard API를 제공해요.

- API 명세: [docs/API.md](docs/API.md)
- 데이터 계약: [contracts/](contracts/) (작업 상태, 응답 예시, 에러 코드)

## 처음 한 번: 설치

Python 3.13이 필요해요. PowerShell에서 저장소 폴더로 이동한 뒤 실행해요.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 서버 실행

새 터미널을 열 때마다 가상환경부터 켜요. 프롬프트 앞에 `(.venv)`가 보이면 켜진 상태예요.

```powershell
.\.venv\Scripts\Activate.ps1
```

**내 PC에서만 개발할 때** (코드를 저장하면 자동 재시작)

```powershell
fastapi dev main.py
```

- Swagger: http://127.0.0.1:8000/docs
- 서버 확인: http://127.0.0.1:8000/health

**폰이나 다른 PC에서 접속할 때** (같은 와이파이)

```powershell
fastapi run main.py
```

- `ipconfig`의 IPv4 주소로 접속해요. 예: `http://192.168.0.10:8000/docs`
- 처음 실행할 때 Windows 방화벽 창이 뜨면 "개인 네트워크" 허용을 눌러요.
- 서버를 켠 PC가 꺼지면 다른 사람도 접속할 수 없어요.

**Flutter 앱을 이 서버에 연결할 때**

```bash
flutter run --dart-define=MICUT_REAL_API=true --dart-define=MICUT_API_URL=http://192.168.0.10:8000
```

Android 에뮬레이터에서는 PC 주소로 `http://10.0.2.2:8000`을 써요.

## 확인

```powershell
python test_flow.py
```

접수 → 처리 → 재시도 → discard 흐름을 임시 폴더에서 확인하고, 통과하면 `ok`를 출력해요.

## 데이터

| 위치 | 내용 |
| --- | --- |
| `micut.db` | 작업 기록 (SQLite) |
| `uploads/` | 원본 사진. 처리가 끝나면 삭제돼요 |
| `results/` | 결과 이미지 |

셋 다 Git에 올라가지 않아요. 서버를 끄고 지우면 초기화돼요.

## 파일 구성

| 파일 | 역할 |
| --- | --- |
| `main.py` | 서버 시작점. 라우터, 에러 처리, 이미지 경로 등록 |
| `routers/jobs.py` | 작업 API 4개 (접수, 조회, 재시도, discard) |
| `schemas.py` | 작업(Job) 응답 모양 |
| `store.py` | 작업 기록 저장 (SQLite) |
| `errors.py` | 모든 실패 응답을 `contracts/error_codes.json` 모양으로 통일 |
| `fake_ai.py` | **AI 연결 전 시연용 가짜 처리.** 실제 AI는 여기와 `routers/jobs.py`의 `TODO(박유진)` 자리에 붙어요 |
