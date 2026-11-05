from fastapi import FastAPI

import errors
import files
from routers import jobs

app = FastAPI(title="MiCut Backend")
errors.register(app)
app.include_router(jobs.router)
files.mount(app)


@app.get("/health")
def health():
    return {"status": "ok"}

