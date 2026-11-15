import { useCallback, useEffect, useRef } from "react";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

export const REFRESH_WINDOW_MS = 300;

export function useEventRefresh(keys: readonly QueryKey[]): () => void {
  const queryClient = useQueryClient();
  const keysRef = useRef(keys);
  keysRef.current = keys;
  const pendingRef = useRef(new Map<string, QueryKey>());
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      pendingRef.current.clear();
    },
    [],
  );

  return useCallback(() => {
    for (const key of keysRef.current) {
      pendingRef.current.set(JSON.stringify(key), key);
    }
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      const queued = [...pendingRef.current.values()];
      pendingRef.current.clear();
      for (const queryKey of queued) {
        void queryClient.invalidateQueries({ queryKey });
      }
    }, REFRESH_WINDOW_MS);
  }, [queryClient]);
}
