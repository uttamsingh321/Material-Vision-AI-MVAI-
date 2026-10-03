# Material Vision AI (MVAI)

## Project Overview and Purpose
Material Vision AI (MVAI) is a sophisticated image recognition and management platform designed to parse, classify, verify, and catalog material assets. By leveraging AI-driven pipelines, the system processes batch uploads (e.g., via Excel), searches for visual candidates from various providers, runs verification checks against designated thresholds, and archives verified assets into a localized image library, finally exporting the collated data.

## Architecture Diagram
```text
+-------------------+        +--------------------+       +----------------------+
|                   |        |                    |       |                      |
|  Frontend (React) +------->+  Backend (FastAPI) +<----->+ SQLite (mvai.db)     |
|                   |        |                    |       |                      |
+--------+----------+        +---------+----------+       +----------------------+
         |                             |
         | uploads                     | orchestrates
         v                             v
+-------------------+        +---------+----------+       +----------------------+
|                   |        |                    |       |                      |
| Local File System |<-------+ Core Pipeline      +------>+ Provider APIs (Mock) |
| (Uploads/Exports) |        | (Search/Verify)    |       |                      |
+-------------------+        +--------------------+       +----------------------+
```

## Quick Start Instructions
### Dev Server (Local)
1. Ensure Python 3.11+ and Node.js 20+ are installed.
2. Run `.\scripts\dev.ps1` to spin up the backend (port 8000) and frontend (port 5173).

### Docker (Production-Ready)
1. Ensure Docker and Docker Compose are installed.
2. Run `docker-compose up --build -d` to spin up the entire stack.
3. Access Frontend at `http://localhost:3000` and API at `http://localhost:8000`.

## Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `APP_ENV` | Application environment (development/production) | `development` |
| `SECRET_KEY` | Secret key for encryption/auth | `change-me-in-production` |
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///./mvai.db` |
| `MAX_UPLOAD_MB` | Maximum allowed file upload size | `50` |
| `MAX_WORKERS` | Number of concurrent workers for jobs | `4` |
| `CONFIDENCE_THRESHOLD` | Threshold for automatic verification acceptance | `0.75` |
| `ALLOWED_ORIGINS` | CORS allowed origins | `http://localhost:3000` |
| `LOG_LEVEL` | Application logging level | `INFO` |

## API Endpoints Summary
- `GET /health` : Healthcheck endpoint.
- `POST /api/upload` : Upload an Excel file for processing.
- `GET /api/jobs` : List processing jobs.
- `GET /api/jobs/{id}` : Get job details.
- `POST /api/jobs/{id}/cancel` : Cancel a job.
- `GET /api/library` : List stored images.
- `GET /api/exports` : Download processed Excel outputs.

## Testing Instructions
Run tests manually using the test script:
```powershell
.\scripts\test.ps1
```
Or directly via pytest:
```bash
python -m pytest backend/tests/ -v --tb=short
```

## Project Structure
```text
.
├── backend/            # FastAPI application
│   ├── app/            # Source code (models, routes, core, services)
│   ├── tests/          # Pytest suite
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           # React + Vite application
│   ├── src/            # Components, pages, hooks
│   ├── package.json
│   ├── nginx.conf
│   └── Dockerfile
├── docs/               # Architecture and API documentation
├── scripts/            # Helper scripts (dev, test)
├── uploads/            # Temporary file uploads
├── exports/            # Generated outputs
├── image-library/      # Final accepted images
└── docker-compose.yml  # Docker orchestration
```

## Tech Stack
| Component | Technology |
|-----------|------------|
| Backend | Python 3.11, FastAPI, SQLAlchemy, SQLite, Pytest |
| Frontend | Node 20, React, Vite, TypeScript, TailwindCSS |
| Deployment| Docker, Nginx |

## Contributing
Please refer to the `CONTRIBUTING.md` (coming soon) for guidelines on branching, linting, and testing before opening a pull request.
