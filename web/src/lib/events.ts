import type { Connection } from "./connection";

export type ServerEvent = {
  id: string | null;
  event: string;
  data: unknown;
};

export type EventStatus = "connecting" | "open" | "reconnecting" | "closed";

export type EventStreamResponse = {
  ok: boolean;
  status: number;
  body: ReadableStream<Uint8Array> | null;
};

export type FetchEventStream = (
  url: string,
  init: RequestInit,
) => Promise<EventStreamResponse>;

export type ConnectEventsOptions = {
  fetchImpl?: FetchEventStream;
  baseDelayMs?: number;
  maxDelayMs?: number;
};

export type ConnectEventsHandlers = {
  onEvent: (event: ServerEvent) => void;
  onStatus?: (status: EventStatus) => void;
};

export type EventsSubscription = {
  stop(): void;
};

type FrameState = {
  id: string | null;
  event: string;
  data: string[];
};

function emptyFrame(): FrameState {
  return { id: null, event: "", data: [] };
}

function applyLine(frame: FrameState, line: string): void {
  if (line.startsWith(":")) return;
  const colon = line.indexOf(":");
  const field = colon === -1 ? line : line.slice(0, colon);
  let value = colon === -1 ? "" : line.slice(colon + 1);
  if (value.startsWith(" ")) value = value.slice(1);
  if (field === "id") frame.id = value;
  else if (field === "event") frame.event = value;
  else if (field === "data") frame.data.push(value);
}

function dispatchFrame(frame: FrameState, onEvent: (event: ServerEvent) => void): void {
  if (frame.data.length === 0) return;
  const payload = frame.data.join("\n");
  if (payload === "") return;
  let parsed: unknown;
  try {
    parsed = JSON.parse(payload);
  } catch {
    return;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return;
  onEvent({
    id: frame.id,
    event: frame.event === "" ? "message" : frame.event,
    data: parsed,
  });
}

export function parseEventChunk(
  buffer: string,
  onEvent: (event: ServerEvent) => void,
): { remainder: string } {
  let frame = emptyFrame();
  let frameStart = 0;
  let cursor = 0;
  while (cursor < buffer.length) {
    const char = buffer[cursor];
    if (char === "\n") {
      dispatchFrame(frame, onEvent);
      frame = emptyFrame();
      cursor += 1;
      frameStart = cursor;
      continue;
    }
    if (char === "\r") {
      if (cursor + 1 >= buffer.length) break;
      cursor += buffer[cursor + 1] === "\n" ? 2 : 1;
      dispatchFrame(frame, onEvent);
      frame = emptyFrame();
      frameStart = cursor;
      continue;
    }
    let end = cursor;
    while (end < buffer.length && buffer[end] !== "\n" && buffer[end] !== "\r") end += 1;
    if (end >= buffer.length) break;
    if (buffer[end] === "\r" && end + 1 >= buffer.length) break;
    applyLine(frame, buffer.slice(cursor, end));
    cursor = buffer[end] === "\r" && buffer[end + 1] === "\n" ? end + 2 : end + 1;
  }
  return { remainder: buffer.slice(frameStart) };
}

export function connectEvents(
  connection: Connection,
  handlers: ConnectEventsHandlers,
  options: ConnectEventsOptions = {},
): EventsSubscription {
  const baseDelay = options.baseDelayMs ?? 1000;
  const maxDelay = options.maxDelayMs ?? 30000;
  const fetchImpl: FetchEventStream = options.fetchImpl ?? ((url, init) => fetch(url, init));
  const endpoint = `${connection.url}/api/events`;

  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;
  let lastEventId: string | null = null;
  let delay = baseDelay;

  const report = (status: EventStatus) => handlers.onStatus?.(status);

  const handleEvent = (event: ServerEvent) => {
    if (event.id !== null && event.id !== "") lastEventId = event.id;
    handlers.onEvent(event);
  };

  const wait = (ms: number) =>
    new Promise<void>((resolve) => {
      timer = setTimeout(() => {
        timer = null;
        resolve();
      }, ms);
    });

  const run = async (): Promise<void> => {
    while (!stopped) {
      controller = new AbortController();
      const headers: Record<string, string> = {
        Authorization: `Bearer ${connection.token}`,
        Accept: "text/event-stream",
      };
      if (lastEventId !== null) headers["Last-Event-ID"] = lastEventId;
      try {
        const response = await fetchImpl(endpoint, { headers, signal: controller.signal });
        if (!response.ok || response.body === null) throw new Error("event stream unavailable");
        report("open");
        delay = baseDelay;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = parseEventChunk(buffer, handleEvent).remainder;
        }
      } catch {
        if (stopped) return;
      }
      if (stopped) return;
      report("reconnecting");
      const current = delay;
      delay = Math.min(delay * 2, maxDelay);
      await wait(current);
    }
  };

  report("connecting");
  void run();

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      controller?.abort();
      report("closed");
    },
  };
}
