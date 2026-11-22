import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (updater: (prev: T | undefined) => T | undefined) => void;
}

/** Last successful answer per `cacheKey`, kept for the lifetime of the tab. */
const responseCache = new Map<string, unknown>();

/**
 * Run an async loader on mount and whenever `deps` change; ignore stale responses.
 *
 * With a `cacheKey` the last answer for that key is shown immediately (also after navigating
 * away and back) while the loader runs again in the background, so `loading` can be true
 * while `data` is already set; `error` reports a failed refresh without clearing `data`.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], cacheKey?: string): AsyncState<T> {
  const cached = () => (cacheKey ? (responseCache.get(cacheKey) as T | undefined) : undefined);
  // The value remembers which key it belongs to, so a key change (e.g. another repo) never
  // shows the previous entity's data, not even for one render.
  const [state, setState] = useState<{ key: string | undefined; value: T | undefined }>(
    () => ({ key: cacheKey, value: cached() }),
  );
  const data = state.key === cacheKey ? state.value : cached();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((result) => {
        if (cacheKey) responseCache.set(cacheKey, result);
        if (!cancelled) setState({ key: cacheKey, value: result });
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, cacheKey, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const setData = useCallback(
    (updater: (prev: T | undefined) => T | undefined) =>
      setState((prev) => {
        const base = prev.key === cacheKey
          ? prev.value
          : cacheKey ? (responseCache.get(cacheKey) as T | undefined) : undefined;
        const next = updater(base);
        if (cacheKey && next !== undefined) responseCache.set(cacheKey, next);
        return { key: cacheKey, value: next };
      }),
    [cacheKey],
  );
  return { data, error, loading, reload, setData };
}

const rtf = new Intl.RelativeTimeFormat("tr", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return "az önce";
}
