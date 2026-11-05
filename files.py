"""사진 파일 보관. uploads/(원본)와 results/(결과) 두 폴더를 쓴다.

SUPABASE_URL이 있으면 Supabase Storage(공개 버킷)에, 없으면 내 PC의 폴더에 저장한다.
"""
import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
BUCKET = os.environ.get("SUPABASE_BUCKET", "micut")
FOLDERS = ("uploads", "results")
CONTENT_TYPES = {".jpg": "image/jpeg", ".png": "image/png"}

if SUPABASE_URL:
    key = os.environ["SUPABASE_KEY"]
    client = httpx.Client(
        base_url=f"{SUPABASE_URL}/storage/v1/object",
        headers={"Authorization": f"Bearer {key}", "apikey": key},
        timeout=30,
    )
else:
    for folder in FOLDERS:
        Path(folder).mkdir(exist_ok=True)


def save(folder: str, name: str, data: bytes) -> None:
    if SUPABASE_URL:
        headers = {"Content-Type": CONTENT_TYPES[Path(name).suffix], "x-upsert": "true"}
        client.post(f"/{BUCKET}/{folder}/{name}", content=data, headers=headers).raise_for_status()
    else:
        (Path(folder) / name).write_bytes(data)


def load(folder: str, name: str) -> bytes:
    if SUPABASE_URL:
        r = client.get(f"/{BUCKET}/{folder}/{name}")
        r.raise_for_status()
        return r.content
    return (Path(folder) / name).read_bytes()


def delete(folder: str, name: str) -> None:
    if SUPABASE_URL:
        # 없는 파일을 지워도 Supabase는 성공으로 응답한다.
        client.request("DELETE", f"/{BUCKET}", json={"prefixes": [f"{folder}/{name}"]}).raise_for_status()
    else:
        (Path(folder) / name).unlink(missing_ok=True)


def mount(app: FastAPI) -> None:
    """/uploads/{name}, /results/{name} 주소로 파일을 내려준다. 명세의 상대 경로 image_url을 그대로 유지한다."""
    for folder in FOLDERS:
        if SUPABASE_URL:
            def redirect(name: str, folder: str = folder):
                return RedirectResponse(f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{folder}/{name}")

            app.add_api_route(f"/{folder}/{{name}}", redirect, include_in_schema=False)
        else:
            app.mount(f"/{folder}", StaticFiles(directory=folder), name=folder)
