from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, SessionLocal, engine
from app.routers import supervisors, vks_clusters
from app.seed import seed_if_empty

app = FastAPI(
    title="VCF Agent Portal (prototype)",
    description=(
        "Prototype portal for VCF 9.1 Supervisor agent-pod session "
        "management and VKS cluster lifecycle management, modeled "
        "after VMware Tanzu Mission Control (TMC-SM)."
    ),
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


app.include_router(supervisors.router)
app.include_router(vks_clusters.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Simple static dashboard for manual testing (fetches the API above).
app.mount("/", StaticFiles(directory="static", html=True), name="static")
