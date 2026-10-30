/** Bounded, uncached requests with user-facing failures (including proxy HTML errors). */
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError'; }
}

export async function requestJson<T>(url: string, options: RequestInit = {}, timeoutMs = 10000): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options.signal?.aborted) cancel();
  options.signal?.addEventListener('abort', cancel, { once: true });
  const timeout = setTimeout(cancel, timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal, cache: 'no-store' });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 && !url.startsWith('/api/session') && !options.signal?.aborted && typeof window !== 'undefined') {
        window.dispatchEvent(new Event('ward:session-expired'));
      }
      const fallback = response.status === 401 ? 'เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง'
        : response.status === 403 ? 'บัญชีนี้ไม่มีสิทธิ์เข้าถึงข้อมูลที่เลือก'
          : response.status === 429 ? 'มีคำขอมากเกินไป กรุณารอสักครู่แล้วลองใหม่'
            : response.status >= 500 ? 'เซิร์ฟเวอร์ยังไม่พร้อม กรุณาลองใหม่อีกครั้ง' : 'ทำรายการไม่สำเร็จ กรุณาลองใหม่';
      throw new ApiError(response.status >= 500 ? fallback : typeof result?.detail === 'string' ? result.detail : fallback, response.status);
    }
    if (result === null) throw new Error('ได้รับข้อมูลไม่ครบ กรุณาลองโหลดใหม่');
    return result as T;
  } catch (error) {
    if (controller.signal.aborted) throw new Error('การเชื่อมต่อใช้เวลานานเกินไป กรุณาลองใหม่');
    if (error instanceof TypeError) throw new Error('เชื่อมต่อไม่ได้ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่');
    throw error;
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener('abort', cancel);
  }
}

export interface UnreadChatSummary {
  summary: Record<string, number>;
  total_unread: number;
  unread_by_patient: Record<string, number>;
  [key: string]: unknown;
}

export async function fetchUnreadChatSummary(options: RequestInit = {}): Promise<UnreadChatSummary> {
  return requestJson<UnreadChatSummary>('/api/care-chat/unread-summary', options);
}

export interface TaskHistoryItem {
  id?: number;
  task_id: number;
  plan_id?: number;
  patient_id?: string;
  previous_state: string;
  new_state: string;
  actor: string;
  skip_reason?: string | null;
  timestamp: number;
  created_at: number;
}

export interface TaskHistoryResponse {
  task_id: number;
  patient_id?: string;
  history: TaskHistoryItem[];
}

export async function fetchTaskHistory(taskId: number, options: RequestInit = {}): Promise<TaskHistoryResponse> {
  return requestJson<TaskHistoryResponse>(`/api/care/tasks/${taskId}/history`, options);
}

export async function fetchCareTaskHistory(taskId: number, options: RequestInit = {}): Promise<TaskHistoryResponse> {
  return fetchTaskHistory(taskId, options);
}

export interface OverdueCareSummary {
  overdue_count: number;
  upcoming_count: number;
  total_open: number;
  [key: string]: unknown;
}

export async function fetchOverdueCareSummary(patientId?: string, options: RequestInit = {}): Promise<OverdueCareSummary> {
  const query = patientId ? `?patient_id=${encodeURIComponent(patientId)}` : '';
  return requestJson<OverdueCareSummary>(`/api/care/overdue-summary${query}`, options);
}

export interface ShiftHandoffSummary {
  generated_at: number;
  care_summary: OverdueCareSummary;
  chat_summary: {
    total_unread: number;
    unread_by_patient: Record<string, number>;
    summary?: Record<string, number>;
    [key: string]: unknown;
  };
  open_alerts_count: number;
  [key: string]: unknown;
}

export async function fetchShiftHandoffSummary(options: RequestInit = {}): Promise<ShiftHandoffSummary> {
  return requestJson<ShiftHandoffSummary>('/api/operations/shift-handoff', options);
}
