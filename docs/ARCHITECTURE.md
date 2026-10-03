# System Architecture

## System Overview
Material Vision AI (MVAI) operates as a split-stack application: a React-based frontend providing a responsive UI, and a Python (FastAPI) backend handling asynchronous orchestration, background workers, image processing pipelines, and data storage via SQLite.

## Component Diagram
```text
+-------------------------------------------------------------+
|                          FRONTEND                           |
|  [ Upload Component ] [ Job Dashboard ] [ Image Library ]   |
+------------------------------+------------------------------+
                               | REST API
+------------------------------v------------------------------+
|                          BACKEND                            |
|                                                             |
|  [ API Layer (FastAPI) ]                                    |
|          |                                                  |
|  [ Orchestration Layer (JobManager, Scheduler, Workers) ]   |
|          |                                                  |
|  [ Pipeline Layer (SearchPipeline, VerificationPipeline) ]  |
|          |                                                  |
|  [ Storage Layer (SQLite DB, File System) ]                 |
+-------------------------------------------------------------+
```

## Data Flow
1. **Upload:** User uploads an Excel file via Frontend -> `POST /api/upload`.
2. **Parse:** Backend parses the XLSX rows into raw item definitions.
3. **Job:** A Job is created in the database and submitted to the Orchestration Layer.
4. **Pipeline (Search):** Worker executes a `SearchPipeline` to find image candidates from registered Providers (e.g., Mock Provider).
5. **Pipeline (Verify):** `VerificationPipeline` evaluates candidate images, scoring them. If score > threshold, they are accepted.
6. **Library:** Accepted images are hashed and stored in the localized `image-library` folder, preventing duplicates.
7. **Export:** A final annotated Excel file with image links/status is written to the `exports` folder.

## Service Responsibilities
| Component | Responsibility |
|-----------|----------------|
| **Job Manager** | Orchestrates lifecycle of batch jobs (Start, Pause, Cancel). |
| **Worker Pool** | Manages concurrent execution of item processing tasks. |
| **Event Bus** | Emits pub/sub events for decouple state tracking (e.g., job progress). |
| **Pipelines** | Encapsulates the business logic of Searching and Verifying materials. |
| **Provider Registry**| Interfaces with external data sources for fetching candidates. |

## API Layer
The API is built on FastAPI. It handles synchronous request/response cycles while offloading heavy tasks to the asyncio background worker pool. Endpoints return Pydantic-validated JSON.

## Frontend Component Tree
```text
App
 ├── Navbar
 ├── Dashboard
 │    ├── UploadWidget
 │    └── ActiveJobsList
 ├── JobDetails
 │    ├── ProgressIndicator
 │    └── ItemDataGrid
 └── LibraryBrowser
      ├── SearchBar
      └── ImageGrid
```

## Key Design Decisions
- **SQLite for Dev/Prod (Phase 1):** Selected for zero-setup portability. Sufficient for single-tenant volume.
- **Mock Providers:** Implemented to isolate testing and pipeline development from external API rate limits or costs.
- **Pure Python Tests:** Ensured the CI/CD pipeline remains lightweight, dodging heavy bindings (like OpenCV/Tesseract) until actual deep-learning models are integrated in later phases.
- **Event Bus Orchestration:** Allows decoupled components (API routes vs background workers) to communicate job progress seamlessly.
