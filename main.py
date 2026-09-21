from dotenv import load_dotenv
load_dotenv()

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers import candidate, recruiter, admin, mcq

app = FastAPI(title="TalentScout API")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(candidate.router)
app.include_router(recruiter.router)
app.include_router(admin.router)
app.include_router(mcq.router)

@app.get("/")
def serve_frontend():
    return FileResponse("static/candidate/index.html")


@app.get("/recruiter")
def serve_recruiter_frontend():
    return FileResponse("static/recruiter/recruiter.html")

@app.get("/login")
def serve_login_frontend():
    return FileResponse("static/login/login.html")

@app.get("/admin")
def serve_admin_frontend():
    return FileResponse("static/admin/admin.html")

@app.get("/screen/{org_slug}")
def serve_org_screening_page(org_slug: str):
    return FileResponse("static/candidate/index.html")