"use client";

import { useCallback, useEffect, useState } from 'react';
import { ApiError, requestJson } from './apiRequest';

type ResourceState<T> = { url: string | null; data: T | null; error: string; loading: boolean; updatedAt: number | null };

/** Sequential polling, finite request timeout, and no stale response after unmount. */
export function usePatientResource<T>(url: string | null, interval = 0, retainOnError = false, pauseWhenHidden = false) {
  const [state, setState] = useState<ResourceState<T>>({ url, data: null, error: '', loading: Boolean(url), updatedAt: null });
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => setRevision((n) => n + 1), []);
  useEffect(() => {
    if (!url) return;
    const endpoint = url;
    let stopped = false;
    let inFlight = false;
    let next: ReturnType<typeof setTimeout> | undefined;
    let current: AbortController | undefined;
    async function load() {
      if (stopped || inFlight || (pauseWhenHidden && document.hidden)) return;
      inFlight = true;
      clearTimeout(next);
      current = new AbortController();
      setState(previous => ({ url: endpoint, data: previous.url === endpoint ? previous.data : null, error: previous.url === endpoint ? previous.error : '', updatedAt: previous.url === endpoint ? previous.updatedAt : null, loading: true }));
      try {
        const result = await requestJson<T>(endpoint, { signal: current.signal });
        if (!stopped) setState({ url: endpoint, data: result, error: '', loading: false, updatedAt: Date.now() });
      } catch (e) {
        const canRetain = retainOnError && !(e instanceof ApiError && [401, 403].includes(e.status));
        if (!stopped) setState(previous => ({ url: endpoint, data: canRetain && previous.url === endpoint ? previous.data : null, error: e instanceof Error ? e.message : 'เชื่อมต่อไม่สำเร็จ กรุณาลองใหม่', updatedAt: previous.url === endpoint ? previous.updatedAt : null, loading: false }));
      } finally {
        inFlight = false;
        if (!stopped && interval) next = setTimeout(load, interval);
      }
    }
    const resume = () => { if (!document.hidden) void load(); };
    void load();
    if (pauseWhenHidden) document.addEventListener('visibilitychange', resume);
    return () => { stopped = true; clearTimeout(next); current?.abort(); document.removeEventListener('visibilitychange', resume); };
  }, [url, interval, revision, retainOnError, pauseWhenHidden]);
  // A URL identifies a patient/time range. Never expose a previous URL's data, even for one render.
  return { ...(state.url === url ? state : { data: null, error: '', loading: Boolean(url), updatedAt: null }), refresh };
}
