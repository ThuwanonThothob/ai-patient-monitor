/** UI freshness is separate from a severity label: stale never means normal. */
export function isFreshReading(reading: { timestamp?: number; status?: string } | undefined, now: number): boolean {
  if (!reading || !Number.isFinite(now) || now <= 0 || !Number.isFinite(reading.timestamp) || !reading.timestamp) return false;
  const age = now - reading.timestamp;
  return age >= -2 && age <= 15 && !["STALE_DATA", "WAITING", "INVALID_DATA"].includes(reading.status ?? "WAITING");
}
