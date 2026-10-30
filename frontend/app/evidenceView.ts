export const vitalKeys = ["heart_rate", "spo2", "respiratory_rate"] as const;
export type Vital = typeof vitalKeys[number];
export type Point = { second: number } & Record<Vital, number | null>;
export function replayChart(input: Point[], observed: Point[], target: number, forecast: number | null, baseline: number | null, key: Vital) {
  const points = [...input, ...observed].map((p) => ({ second: p.second, actual: p[key], forecast: null as number | null, baseline: null as number | null }));
  const anchor = points[input.length - 1];
  if (anchor && forecast !== null) {
    anchor.forecast = anchor.actual; anchor.baseline = baseline;
    const end = points.find((p) => p.second === target);
    if (end) { end.forecast = forecast; end.baseline = baseline; }
    else points.push({ second: target, actual: null, forecast, baseline });
  }
  return points;
}
export function metric(value?: number | null, digits = 2) { return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits); }
