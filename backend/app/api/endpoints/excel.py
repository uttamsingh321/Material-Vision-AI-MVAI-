from fastapi import APIRouter

router = APIRouter()

@router.post("/review")
async def review():
    return {"status": "reviewed"}

@router.get("/export")
async def export():
    return {"data": "mock_export"}
