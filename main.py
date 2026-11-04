from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import errors
from routers import jobs

app = FastAPI(title="MiCut Backend")
errors.register(app)
app.include_router(jobs.router)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/results", StaticFiles(directory="results"), name="results")


@app.get("/health")
def health():
    return {"status": "ok"}

