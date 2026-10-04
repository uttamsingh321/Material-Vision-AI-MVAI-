from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from app.services.excel_parser import spreadsheet_parser
import asyncio
from typing import List, Dict, Any
import openpyxl
from fastapi import BackgroundTasks
import datetime
import os
import re
import httpx
import urllib.parse

from app.api.endpoints.job_state_mock import create_job, update_job_progress, add_image
from crawler.providers import DigikeyProvider
from crawler.multi_engine import MultiEngineImagesProvider
from crawler.base import SearchQuery

app = FastAPI(title="Material Vision AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.endpoints import jobs
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])

active_connections: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

async def broadcast_ws(message: Dict[str, Any]):
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except:
            pass

def extract_core_keywords(description: str) -> str:
    if not description: return ""
    parts = re.split(r'[_|,]', str(description))
    core = parts[0].strip()
    # Strip garbage characters: question marks, garbage symbols, non-printable chars
    core = re.sub(r'[?？！@#$%^&*=\[\]{}<>~`\\]+', '', core)
    core = re.sub(r'\s+', ' ', core).strip()
    words = core.split()
    if len(words) > 6:
        core = " ".join(words[:6])
    return core

async def process_excel_background(input_path: str, filename: str, job_id: int):
    try:
        wb = openpyxl.load_workbook(input_path)
        ws = wb.active
        
        digikey = DigikeyProvider()
        playwright_fallback = MultiEngineImagesProvider()
        playwright_fallback.enabled = True
        
        if digikey.enabled:
            await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Using DigiKey API (fast mode, 5x concurrent)"})
            # Pre-fetch token to avoid race condition in threads
            try:
                await digikey._get_token()
            except Exception:
                pass
        else:
            await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Using Bing Stealth browser (standard mode, 5x concurrent)"})
        
        img_col = 7
        img_col_letter = chr(64 + img_col)
        ws.column_dimensions[img_col_letter].width = 15
        
        # Load persistent cache to "train" the model to be faster across runs
        import json
        import os
        CACHE_FILE = "search_cache.json"
        global_cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    global_cache = json.load(f)
            except Exception:
                pass

        # Deduplicate rows by material description
        material_rows = {}
        for row in range(2, ws.max_row + 1):
            raw_desc = ws.cell(row=row, column=5).value or ws.cell(row=row, column=4).value or ws.cell(row=row, column=3).value
            if not raw_desc: continue
            
            material_desc = extract_core_keywords(raw_desc)
            if not material_desc: continue
            
            if material_desc not in material_rows:
                material_rows[material_desc] = []
            material_rows[material_desc].append(row)
        
        total_unique = len(material_rows)
        if total_unique == 0:
            return
            
        completed_unique = 0
        semaphore = asyncio.Semaphore(5)
        
        import os
        import hashlib
        CACHE_DIR = "image-cache"
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)
            
        async def process_single(desc, retry_prefix=""):
            img_url = None
            is_cached = False
            lookup_key = desc if not retry_prefix else f"{retry_prefix}:{desc}"

            if lookup_key in global_cache:
                img_url = global_cache[lookup_key]
                is_cached = True
            elif desc in global_cache:
                img_url = global_cache[desc]
                is_cached = True
            else:
                async with semaphore:
                    try:
                        search_text = f"{retry_prefix} {desc}".strip() if retry_prefix else desc
                        await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {'↩ Retrying' if retry_prefix else 'Searching'}: {search_text}"})
                        query = SearchQuery(text=str(search_text))
                        resp = None
                        
                        if digikey.enabled:
                            try:
                                resp = await digikey.search(query)
                            except Exception:
                                resp = None
                        
                        if not resp or not resp.hits:
                            resp = await playwright_fallback.search(query)
                        
                        if resp and resp.hits:
                            img_url = resp.hits[0].image_url
                        else:
                            return desc, "not_found", None, None, None
                    except Exception as e:
                        return desc, "error", None, None, str(e)
            
            if img_url:
                try:
                    safe_name = hashlib.md5(img_url.encode('utf-8')).hexdigest() + ".jpg"
                    cached_path = os.path.join(CACHE_DIR, safe_name)
                    
                    img_bytes = None
                    if os.path.exists(cached_path):
                        with open(cached_path, "rb") as f:
                            img_bytes = f.read()
                    else:
                        img_bytes = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: httpx.get(img_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bing.com/"}, timeout=8, follow_redirects=True).content
                        )
                        with open(cached_path, "wb") as f:
                            f.write(img_bytes)
                            
                    if is_cached:
                        return desc, "found_cache", img_url, img_bytes, None
                    return desc, "found", img_url, img_bytes, None
                except Exception as img_err:
                    return desc, "found_no_img", img_url, None, str(img_err)
            return desc, "not_found", None, None, None

        # ---- PASS 1: Search all items ----
        pending_tasks = [asyncio.create_task(process_single(desc)) for desc in material_rows.keys()]
        
        import io
        from openpyxl.drawing.image import Image as XLImage

        not_found_items = []  # collect items to retry

        for completed_task in asyncio.as_completed(pending_tasks):
            material_desc, status, img_url, img_bytes, err = await completed_task
            rows_to_update = material_rows[material_desc]
            
            for row in rows_to_update:
                if status in ["found", "found_cache"]:
                    try:
                        # Must create new XLImage instance per cell
                        img_stream = io.BytesIO(img_bytes)
                        xl_img = XLImage(img_stream)
                        xl_img.width = 80
                        xl_img.height = 80
                        cell_addr = f"{img_col_letter}{row}"
                        ws.add_image(xl_img, cell_addr)
                        ws.row_dimensions[row].height = 65
                    except Exception:
                        pass
                elif status == "found_no_img":
                    pass
                elif status == "error":
                    pass
            
            if status in ["found", "found_no_img"]:
                if status == "found":
                    add_image(material_desc, img_url)
                global_cache[material_desc] = img_url
                await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Found: {img_url}"})
            elif status == "found_cache":
                await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Cached: Skipped {material_desc}"})
            if status in ["not_found", "error"]:
                not_found_items.append(material_desc)
            
            completed_unique += 1
            progress_pct = int((completed_unique / total_unique) * 100)
            update_job_progress(job_id, progress_pct)
            
            from app.api.endpoints.job_state_mock import background_jobs
            job_data = background_jobs.get(job_id)
            if job_data:
                await broadcast_ws({
                    "type": "job_update",
                    "data": {
                        "id": job_id,
                        "progress": progress_pct,
                        "speed": 300,
                        "eta": "Unknown",
                        "total_items": ws.max_row - 1
                    }
                })

        # ---- PASS 2: Retry not-found items with alternative query prefixes ----
        retry_strategies = ["product image of", "photo of", ""]
        for retry_prefix in retry_strategies:
            if not not_found_items:
                break
            await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ↩ Retrying {len(not_found_items)} items (prefix: '{retry_prefix}')..."})
            retry_tasks = [asyncio.create_task(process_single(desc, retry_prefix)) for desc in not_found_items]
            still_not_found = []
            for completed_task in asyncio.as_completed(retry_tasks):
                material_desc, status, img_url, img_bytes, err = await completed_task
                rows_to_update = material_rows[material_desc]
                if status in ["found", "found_cache"]:
                    for row in rows_to_update:
                        try:
                            img_stream = io.BytesIO(img_bytes)
                            xl_img = XLImage(img_stream)
                            xl_img.width = 80
                            xl_img.height = 80
                            ws.add_image(xl_img, f"{img_col_letter}{row}")
                            ws.row_dimensions[row].height = 65
                        except Exception:
                            pass
                    if status == "found":
                        add_image(material_desc, img_url)
                    global_cache[material_desc] = img_url
                    await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✓ Retry Found: {material_desc}"})
                else:
                    still_not_found.append(material_desc)
            not_found_items = still_not_found

        if not_found_items:
            await broadcast_ws({"type": "log", "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⚠ {len(not_found_items)} items had no images across all engines."})

        # Save cache to disk
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(global_cache, f)
        except Exception:
            pass
            
        output_path = f"output_{filename}"
        wb.save(output_path)
        print(f"Background processing complete! File saved as: {output_path}")
        update_job_progress(job_id, 100)
        await broadcast_ws({
            "type": "log",
            "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✅ Processing complete! Saved to {output_path}"
        })
        update_job_progress(job_id, 100)
        await broadcast_ws({
            "type": "log",
            "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Processing complete! Saved to {output_path}"
        })
    except Exception as e:
        print(f"Background processing failed: {e}")
        await broadcast_ws({
            "type": "log",
            "data": f"[{datetime.datetime.now().strftime('%H:%M:%S')}] FATAL ERROR: {str(e)}"
        })

@app.post("/api/upload")
async def upload_material_excel(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file type.")

    content = await file.read()
    input_path = f"temp_input_{file.filename}"
    with open(input_path, "wb") as f:
        f.write(content)
        
    try:
        wb = openpyxl.load_workbook(input_path)
        total_items = wb.active.max_row - 1
    except Exception:
        total_items = 100
        
    job_id = create_job(file.filename, total_items)
    background_tasks.add_task(process_excel_background, input_path, file.filename, job_id)
    
    return {
        "message": f"Upload successful! Processing in background.",
        "filename": file.filename,
        "job_id": job_id,
    }

@app.get("/api/proxy-image")
async def proxy_image(url: str):
    """Proxies external image URLs to avoid CORS issues in the browser."""
    try:
        decoded_url = urllib.parse.unquote(url)
        
        # Try serving from local cache first!
        import hashlib, os
        safe_name = hashlib.md5(decoded_url.encode('utf-8')).hexdigest() + ".jpg"
        cached_path = os.path.join("image-cache", safe_name)
        
        if os.path.exists(cached_path):
            with open(cached_path, "rb") as f:
                content = f.read()
            return StreamingResponse(iter([content]), media_type="image/jpeg")
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bing.com/"
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(decoded_url, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return StreamingResponse(
                iter([resp.content]),
                media_type=content_type
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch image: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)

@app.get("/api/download/latest")
async def download_latest_output():
    import os
    import glob
    from fastapi.responses import FileResponse
    
    files = glob.glob("output_*.xlsx")
    if not files:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No output file found")
        
    latest_file = max(files, key=os.path.getctime)
    return FileResponse(
        path=latest_file,
        filename="Processed_Material_Master.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
