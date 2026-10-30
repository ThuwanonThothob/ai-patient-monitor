import type { CSSProperties } from "react";

const paths: Record<string, string> = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  triage: "M3 12h4l3-8 4 16 3-8h4",
  patients: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M17 4a4 4 0 0 1 0 7 M22 21v-2a4 4 0 0 0-3-3.87",
  alerts: "M12 3 2 21h20L12 3z M12 9v5 M12 17h.01",
  ai: "M12 3 9 9 3 12l6 3 3 6 3-6 6-3-6-3-3-6z",
  evidence: "M3 20h18 M5 16l4-6 4 3 6-9 M15 4h4v4",
  care: "M9 4H5v18h14V4h-4 M9 2h6v5H9z m-1 11 3 3 5-6",
  research: "M9 3h6 M10 3v6L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3 M7 15h10",
  reports: "M14 2H5v20h14V7l-5-5z M14 2v6h5 M8 12h8 M8 16h6",
  notifications: "M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M10 17h4 M11 6h2",
  chat: "M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z",
  arrow: "M5 12h14 M14 7l5 5-5 5",
  check: "m5 12 4 4L19 6",
  shield: "M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4z m-5 9 3 3 6-6",
};

export default function Icon({ name, size = 20, style }: { name: string; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0, ...style }}><path d={paths[name] ?? paths.overview} /></svg>;
}
