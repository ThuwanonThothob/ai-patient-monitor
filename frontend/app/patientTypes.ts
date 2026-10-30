import type { MonitorData } from './MonitorPanel';
import type { CareVital } from './careView';

export type PatientRecord = {
  patient_id: string; demo: boolean; monitor: MonitorData;
  profile: { name: string; zone: string; room_number: string; bed_number: number; age: number; gender: string; blood_group: string; condition: string; mobility: string; care_setting?: string; care_goal?: string; emergency_contact?: string; doctor?: string; assigned_staff_id?: string };
};
export type MyCare = {
  patient_id: string; as_of: number; profile: { version: number; reviewed_at: number; conditions: string; medications: string; allergies: string; limitations: string } | null;
  plans: { id: number; title: string; instructions: string; state: string; interval_minutes: number; next_due: number; reviewed_at: number }[];
  tasks: { id: number; title: string; instructions: string; state: string; scheduled_at: number; completed_at: number | null; acknowledged_at: number | null; overdue: boolean }[];
  open_count: number; done_today: number; plan_count: number; task_count: number; tasks_truncated: boolean; plans_truncated: boolean;
};
export type Stats = { count: number; mean: number; min: number; max: number; first: number; last: number };
export type MyTrends = {
  patient_id: string; hours: number; start: number; as_of: number; bucket_seconds: number;
  sources: Record<string, { snapshot_count: number; statistics: Record<CareVital, Stats | null>;
    points: ({ timestamp: number; count: number } & Record<CareVital, number | null>)[];
    coverage: { estimated_percent: number; gap_count: number; longest_gap_seconds: number } }>;
};
export type MyDaily = {
  patient_id: string; day: string; generated_at: number; as_of: number; partial_day: boolean; digest: string; text: string;
  recording: { estimated_percent: number; gap_count: number; longest_gap_seconds: number };
  care: { due_in_period: number; done_in_period: number; open_due_as_of_count: number; skipped_in_period: number; cancelled_in_period: number };
  alerts: { new_count: number; resolved_count: number; open_as_of_count: number };
};
