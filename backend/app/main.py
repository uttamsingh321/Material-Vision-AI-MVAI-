from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.services.excel_parser import spreadsheet_parser

app = FastAPI(title="Material Vision AI", version="1.0.0")

# Setup CORS for the React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify the frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/api/upload")
async def upload_material_excel(file: UploadFile = File(...)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")

    content = await file.read()
    
    try:
        parser = spreadsheet_parser()
        result = parser.parse_bytes(
            data=content,
            batch_id="test-batch-001",
            batch_name=file.filename,
            source_filename=file.filename
        )
        
        # Result typically returns an iterator of materials or an ImportResult object
        # We will exhaust it to get the parsed rows (materials)
        materials = list(result.materials) if hasattr(result, 'materials') else list(result)
        
        return {
            "message": "File processed successfully",
            "filename": file.filename,
            "parsed_rows": len(materials),
            # Returning first 5 parsed materials as a preview
            "preview": [mat.values() if hasattr(mat, 'values') else dict(mat) for mat in materials[:5]] 
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
