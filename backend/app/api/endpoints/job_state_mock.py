import datetime

# Global in-memory dictionary for background tasks
background_jobs = {}

def get_all_jobs():
    return list(background_jobs.values())

def create_job(filename: str, total_items: int) -> int:
    job_id = len(background_jobs) + 1
    background_jobs[job_id] = {
        "id": job_id,
        "batch_id": f"batch_{job_id}_{filename}",
        "job_type": "PROCESS_BATCH",
        "status": "RUNNING",
        "progress": 0,
        "total_items": total_items,
        "processed_items": 0,
        "created_at": datetime.datetime.now().isoformat()
    }
    return job_id

def update_job_progress(job_id: int, processed_items: int):
    if job_id in background_jobs:
        job = background_jobs[job_id]
        job["processed_items"] = processed_items
        if job["total_items"] > 0:
            job["progress"] = min(100, int((processed_items / job["total_items"]) * 100))
        if processed_items >= job["total_items"]:
            job["status"] = "COMPLETED"
            job["progress"] = 100

found_images = []

def add_image(material_name: str, url: str):
    found_images.insert(0, {
        "name": material_name,
        "url": url,
        "timestamp": datetime.datetime.now().isoformat()
    })
    # Keep last 50 images to avoid memory bloat
    if len(found_images) > 50:
        found_images.pop()

def get_images():
    return found_images

def get_stats():
    jobs = list(background_jobs.values())
    running = sum(1 for j in jobs if j["status"] == "RUNNING")
    completed = sum(1 for j in jobs if j["status"] == "COMPLETED")
    failed = sum(1 for j in jobs if j["status"] == "FAILED")
    
    total_materials = sum(j["total_items"] for j in jobs)
    
    recent_activity = []
    for j in reversed(jobs[-5:]): # last 5 jobs
        recent_activity.append({
            "message": f"Job #{j['id']} ({j['status']})",
            "time": j["created_at"]
        })
        
    return {
        "total_materials": total_materials,
        "running_jobs": running,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "recent_activity": recent_activity
    }
