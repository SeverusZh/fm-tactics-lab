import { useEffect, useRef } from "react";

import type { Connection } from "./connection";
import { connectEvents, type EventStatus, type ServerEvent } from "./events";

export function useAppEvents(
  connection: Connection | null,
  handler: (event: ServerEvent) => void,
  onStatus?: (status: EventStatus) => void,
): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const statusRef = useRef(onStatus);
  statusRef.current = onStatus;

  const url = connection?.url ?? null;
  const token = connection?.token ?? null;
  const api = connection?.api ?? null;

  useEffect(() => {
    if (url === null || token === null || api === null) return;
    const subscription = connectEvents(
      { url, token, api },
      {
        onEvent: (event) => handlerRef.current(event),
        onStatus: (status) => statusRef.current?.(status),
      },
    );
    return () => subscription.stop();
  }, [url, token, api]);
}
