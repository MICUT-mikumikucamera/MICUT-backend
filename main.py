from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import errors
import files
from routers import collection, jobs

app = FastAPI(title="MiCut Backend")
# Flutter 웹(브라우저)에서 다른 주소의 이 서버를 부를 수 있게 허용한다. 로그인·쿠키가 없어서 모든 출처를 허용해도 된다.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
errors.register(app)
app.include_router(jobs.router)
app.include_router(collection.router)
files.mount(app)


@app.get("/health")
def health():
    return {"status": "ok"}

