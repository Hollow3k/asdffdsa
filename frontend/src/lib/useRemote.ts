import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../services/api";

export type RemoteState<T> =
  | { status: "idle" }
  | { status: "loading"; data?: T }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError; data?: T };

export function toApiError(e: unknown): ApiError {
  if (e instanceof ApiError) return e;
  return new ApiError(e instanceof Error ? e.message : "Unexpected error", "CLIENT_ERROR", 0);
}

/**
 * Runs `fetcher` whenever `key` changes (null fetcher = idle). Responses belonging to a superseded
 * run are discarded so a slow earlier request can never overwrite a newer one.
 */
export function useRemote<T>(fetcher: (() => Promise<T>) | null, key: string): RemoteState<T> & { reload: () => void } {
  const [state, setState] = useState<RemoteState<T>>({ status: fetcher ? "loading" : "idle" });
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const fn = fetcherRef.current;
    if (!fn) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState((prev) => ({ status: "loading", data: "data" in prev ? prev.data : undefined }));
    fn().then(
      (data) => {
        if (!cancelled) setState({ status: "success", data });
      },
      (e: unknown) => {
        if (!cancelled) setState((prev) => ({ status: "error", error: toApiError(e), data: "data" in prev ? prev.data : undefined }));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload } as RemoteState<T> & { reload: () => void };
}
