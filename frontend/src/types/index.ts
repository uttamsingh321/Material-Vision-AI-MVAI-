export interface UploadResponse {
  batch_id: string;
  total_rows: number;
}

export interface BatchDetail {
  batch_id: string;
  total_rows: number;
  materials: MaterialRow[];
}

export interface MaterialRow {
  id: string;
  name: string;
  description?: string;
  status: string;
}

export interface Job {
  id: string;
  name: string;
  status: string;
  batch_id: string;
  created_at: string;
  updated_at: string;
  total_materials: number;
  processed_materials: number;
  accepted_materials: number;
  failed_materials: number;
}

export interface JobStatus {
  status: string;
  progress: number;
}

export interface ProgressSnapshot {
  job_id: string;
  progress: number;
  accepted: number;
  review: number;
  failed: number;
  eta_seconds?: number;
  throughput?: number;
}

export interface ReviewItem {
  id: string;
  job_id: string;
  material_name: string;
  image_url: string;
  confidence_score: number;
  status: 'Pending' | 'Approved' | 'Rejected';
}

export interface PaginatedResult<T> {
  data: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface LibraryItem {
  id: string;
  material_name: string;
  category: string;
  image_url: string;
  confidence_score: number;
  date_added: string;
}

export interface ExportResult {
  export_id: string;
  status: string;
}

export interface ExportStatus {
  export_id: string;
  status: string;
  download_url?: string;
}

export interface Provider {
  id: string;
  name: string;
  status: string;
  enabled: boolean;
  last_checked: string;
}

export interface ProviderHealth {
  status: string;
  latency_ms: number;
  error?: string;
}

export interface AuditLog {
  id: string;
  timestamp: string;
  event_type: string;
  message: string;
  job_id?: string;
}

export interface HealthStatus {
  status: string;
  version: string;
}
