from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.job_manager import JobManager
from app.models.enums import JobType

from app.api.endpoints.job_state_mock import get_all_jobs, get_stats, get_images

router = APIRouter()

# Dummy dependency for now
async def get_session():
    pass

@router.get("/")
async def list_jobs() -> List[Dict[str, Any]]:
    return get_all_jobs()

@router.get("/images")
async def list_images() -> List[Dict[str, Any]]:
    return get_images()

@router.get("/stats")
async def get_dashboard_stats() -> Dict[str, Any]:
    return get_stats()

@router.post("/upload")
async def upload_file():
    return {"job_id": 1}

@router.post("/{job_id}/start")
async def start_job(job_id: int):
    return {"status": "started"}

@router.post("/{job_id}/pause")
async def pause_job(job_id: int):
    return {"status": "paused"}

@router.post("/{job_id}/resume")
async def resume_job(job_id: int):
    return {"status": "resumed"}

@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int):
    return {"status": "cancelled"}

@router.get("/{job_id}/status")
async def get_status(job_id: int):
    return {"status": "PENDING"}

@router.get("/{job_id}/progress")
async def get_progress(job_id: int):
    return {"progress": 0}
