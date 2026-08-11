from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers import candidate, recruiter

app = FastAPI(title="TalentScout API")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(candidate.router)
app.include_router(recruiter.router)


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")


@app.get("/recruiter")
def serve_recruiter_frontend():
    return FileResponse("static/recruiter.html")