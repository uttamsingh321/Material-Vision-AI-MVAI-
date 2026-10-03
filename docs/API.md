# API Documentation

## Endpoints

### General
**`GET /health`**
- **Description:** Basic health check.
- **Response:** `{"status": "ok"}`

### Uploads
**`POST /api/upload`**
- **Description:** Upload an XLSX file.
- **Request Body:** `multipart/form-data` with a `file` field.
- **Response:** `{"job_id": 1, "status": "created", "items_found": 50}`

### Jobs
**`GET /api/jobs`**
- **Description:** List all jobs.
- **Response:** `[{"id": 1, "status": "running", "progress": 45}, ...]`

**`GET /api/jobs/{id}`**
- **Description:** Get specific job details.
- **Response:** `{"id": 1, "status": "completed", "results": [...]}`

**`POST /api/jobs/{id}/cancel`**
- **Description:** Cancel an active job.
- **Response:** `{"id": 1, "status": "cancelled"}`

### Library
**`GET /api/library`**
- **Description:** Browse accepted images.
- **Response:** `[{"hash": "abc...", "url": "/image-library/abc.png"}, ...]`

### Exports
**`GET /api/exports`**
- **Description:** List available processed files.
- **Response:** `[{"filename": "job_1_export.xlsx", "url": "/exports/job_1_export.xlsx"}]`

## Authentication
*(Placeholder)* Future phases will introduce JWT-based authentication via `Authorization: Bearer <token>`.

## Error Codes
- `400 Bad Request`: Invalid file format or missing data.
- `404 Not Found`: Job or Resource not found.
- `500 Internal Server Error`: Pipeline failure or unhandled exception.

## Rate Limiting
Currently, rate limiting is not enforced. When implemented, limits will be returned in standard `X-RateLimit-*` headers.
