import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";

export interface Async<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  /** When the data last arrived successfully. */
  at: Date | null;
}

export function useAsync<T>(load: () => Promise<T>, enabled = true): Async<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean; at: Date | null }>({
    data: null,
    error: null,
    loading: enabled,
    at: null,
  });
  const loader = useRef(load);
  loader.current = load;
  const seq = useRef(0);

  const run = useCallback(() => {
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    loader
      .current()
      .then((data) => {
        if (mine === seq.current) setState({ data, error: null, loading: false, at: new Date() });
      })
      .catch((err) => {
        if (mine === seq.current)
          setState((s) => ({ ...s, error: err instanceof ApiError ? err : new ApiError(0, String(err)), loading: false }));
      });
  }, []);

  useEffect(() => {
    if (enabled) run();
  }, [enabled, run]);

  return { ...state, reload: run };
}
