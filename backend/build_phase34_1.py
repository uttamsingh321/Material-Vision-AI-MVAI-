import os

base_dir = r"c:\Users\uttam.singh1\Desktop\Material Vision AI (MVAI)\backend"
def write_f(path, content):
    full = os.path.join(base_dir, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)

write_f("app/services/event_bus.py", """\
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Literal, Union, List, Callable
from datetime import datetime
import asyncio
from uuid import uuid4

class BaseEvent(BaseModel):
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_id: str = Field(default_factory=lambda: str(uuid4()))

class JobCreatedEvent(BaseEvent):
    event_type: Literal["JOB_CREATED"] = "JOB_CREATED"
    job_id: str
    job_type: str

class JobStartedEvent(BaseEvent):
    event_type: Literal["JOB_STARTED"] = "JOB_STARTED"
    job_id: str
    worker_id: str

class JobStatusEvent(BaseEvent):
    event_type: Literal["JOB_STATUS_CHANGED"] = "JOB_STATUS_CHANGED"
    job_id: str
    status: str

class JobPausedEvent(BaseEvent):
    event_type: Literal["JOB_PAUSED"] = "JOB_PAUSED"
    job_id: str

class JobResumedEvent(BaseEvent):
    event_type: Literal["JOB_RESUMED"] = "JOB_RESUMED"
    job_id: str

class JobCancelledEvent(BaseEvent):
    event_type: Literal["JOB_CANCELLED"] = "JOB_CANCELLED"
    job_id: str

class JobCompletedEvent(BaseEvent):
    event_type: Literal["JOB_COMPLETED"] = "JOB_COMPLETED"
    job_id: str

class JobFailedEvent(BaseEvent):
    event_type: Literal["JOB_FAILED"] = "JOB_FAILED"
    job_id: str
    reason: str

class SearchStartedEvent(BaseEvent):
    event_type: Literal["SEARCH_STARTED"] = "SEARCH_STARTED"
    job_id: str
    query: str

class ProviderCompletedEvent(BaseEvent):
    event_type: Literal["PROVIDER_COMPLETED"] = "PROVIDER_COMPLETED"
    job_id: str
    provider_id: str
    results_count: int

class ImageDownloadedEvent(BaseEvent):
    event_type: Literal["IMAGE_DOWNLOADED"] = "IMAGE_DOWNLOADED"
    job_id: str
    url: str

class OcrCompletedEvent(BaseEvent):
    event_type: Literal["OCR_COMPLETED"] = "OCR_COMPLETED"
    job_id: str

class VerificationCompletedEvent(BaseEvent):
    event_type: Literal["VERIFICATION_COMPLETED"] = "VERIFICATION_COMPLETED"
    job_id: str

class ConfidenceAssignedEvent(BaseEvent):
    event_type: Literal["CONFIDENCE_ASSIGNED"] = "CONFIDENCE_ASSIGNED"
    job_id: str
    score: float

class ImageAcceptedEvent(BaseEvent):
    event_type: Literal["IMAGE_ACCEPTED"] = "IMAGE_ACCEPTED"
    job_id: str

class ImageRejectedEvent(BaseEvent):
    event_type: Literal["IMAGE_REJECTED"] = "IMAGE_REJECTED"
    job_id: str

class ExportCompletedEvent(BaseEvent):
    event_type: Literal["EXPORT_COMPLETED"] = "EXPORT_COMPLETED"
    job_id: str

class ErrorOccurredEvent(BaseEvent):
    event_type: Literal["ERROR_OCCURRED"] = "ERROR_OCCURRED"
    job_id: str
    error_msg: str

Event = Union[JobCreatedEvent, JobStartedEvent, JobStatusEvent, SearchStartedEvent, ProviderCompletedEvent, JobPausedEvent, JobResumedEvent, JobCancelledEvent, JobCompletedEvent, JobFailedEvent, ImageDownloadedEvent, OcrCompletedEvent, VerificationCompletedEvent, ConfidenceAssignedEvent, ImageAcceptedEvent, ImageRejectedEvent, ExportCompletedEvent, ErrorOccurredEvent]

class StructuredEventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._history: List[Event] = []
    
    def subscribe(self, channel: str, callback: Callable):
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
        
    def publish(self, channel: str, event: Event) -> int:
        self._history.append(event)
        if channel in self._subscribers:
            for cb in self._subscribers[channel]:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.create_task(cb(event))
                else:
                    cb(event)
        return len(self._subscribers.get(channel, []))
        
    def get_history(self, limit: int = 100) -> List[Event]:
        return self._history[-limit:]

_structured_bus = None
def get_structured_event_bus() -> StructuredEventBus:
    global _structured_bus
    if _structured_bus is None:
        _structured_bus = StructuredEventBus()
    return _structured_bus
""")
print("Done")
