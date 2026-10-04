# Start backend dev server
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; ..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001"
# Start frontend dev server  
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"
Write-Host 'Backend: http://localhost:8000'
Write-Host 'Frontend: http://localhost:5173'
Write-Host 'API Docs: http://localhost:8000/docs'
