import { afterEach, describe, expect, it, vi } from "vitest";

import {
  connectEvents,
  parseEventChunk,
  type EventStatus,
  type EventStreamResponse,
  type FetchEventStream,
  type ServerEvent,
} from "./events";

const connection = { url: "http://127.0.0.1:43210", token: "test-token", api: "fm27lab/v2" };

function collect() {
  const events: ServerEvent[] = [];
  return { events, onEvent: (event: ServerEvent) => events.push(event) };
}

function parseAll(text: string): ServerEvent[] {
  const { events, onEvent } = collect();
  parseEventChunk(text, onEvent);
  return events;
}

function frameOf(text: string): { remainder: string; events: ServerEvent[] } {
  const { events, onEvent } = collect();
  const { remainder } = parseEventChunk(text, onEvent);
  return { remainder, events };
}

type StreamControl = {
  response: Response;
  send(text: string): void;
  sendBytes(bytes: Uint8Array): void;
  close(): void;
  fail(): void;
};

function controlledStream(): StreamControl {
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  const stream = new ReadableStream<Uint8Array>({
    start(inner) {
      controller = inner;
    },
  });
  return {
    response: new Response(stream),
    send(text) {
      controller?.enqueue(new TextEncoder().encode(text));
    },
    sendBytes(bytes) {
      controller?.enqueue(bytes);
    },
    close() {
      controller?.close();
    },
    fail() {
      controller?.error(new Error("读取失败"));
    },
  };
}

function openResponse(chunks: string[] = []): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
    },
  });
  return new Response(stream);
}

type FetchCall = { url: string; init: RequestInit };
type Responder = () => EventStreamResponse | Promise<EventStreamResponse>;

function recordingFetch(responders: Responder[]): {
  fetchImpl: FetchEventStream;
  calls: FetchCall[];
} {
  const calls: FetchCall[] = [];
  const fetchImpl: FetchEventStream = async (url, init) => {
    calls.push({ url, init });
    const index = Math.min(calls.length - 1, responders.length - 1);
    return responders[index]();
  };
  return { fetchImpl, calls };
}

function headersOf(call: FetchCall | undefined): Headers {
  if (call === undefined) throw new Error("缺少请求");
  return new Headers(call.init.headers);
}

function statusRecorder() {
  const statuses: EventStatus[] = [];
  return { statuses, onStatus: (status: EventStatus) => statuses.push(status) };
}

describe("parseEventChunk", () => {
  it("派发完整帧的 id、event 与 JSON 负载", () => {
    const { remainder, events } = frameOf(
      'id: 7\nevent: job.updated\ndata: {"id":"job-1","status":"running"}\n\n',
    );

    expect(events).toEqual([
      { id: "7", event: "job.updated", data: { id: "job-1", status: "running" } },
    ]);
    expect(remainder).toBe("");
  });

  it("未以空行结束的帧留在 remainder 且不派发", () => {
    const first = frameOf('data: {"id":"job-1"}\n');

    expect(first.events).toEqual([]);
    expect(first.remainder).toBe('data: {"id":"job-1"}\n');

    const second = frameOf(first.remainder + "\n");

    expect(second.events).toEqual([{ id: null, event: "message", data: { id: "job-1" } }]);
    expect(second.remainder).toBe("");
  });

  it("同一块中的多个事件按顺序派发", () => {
    const events = parseAll(
      'event: job.created\ndata: {"id":"a"}\n\nevent: job.deleted\ndata: {"job_id":"b","deleted":true}\n\n',
    );

    expect(events).toEqual([
      { id: null, event: "job.created", data: { id: "a" } },
      { id: null, event: "job.deleted", data: { job_id: "b", deleted: true } },
    ]);
  });

  it("CRLF 分隔的帧可解析", () => {
    const events = parseAll('id: 1\r\nevent: job.updated\r\ndata: {"id":"job-1"}\r\n\r\n');

    expect(events).toEqual([{ id: "1", event: "job.updated", data: { id: "job-1" } }]);
  });

  it("块尾 CR 不提前派发并与下一块 LF 组成 CRLF", () => {
    const first = frameOf('data: {"id":"job-1"}\r');

    expect(first.events).toEqual([]);

    const second = frameOf(first.remainder + "\n\r\n");

    expect(second.events).toEqual([{ id: null, event: "message", data: { id: "job-1" } }]);
    expect(second.remainder).toBe("");
  });

  it("注释行被忽略且不影响后续字段", () => {
    const events = parseAll(': keepalive\n\ndata: {"id":"job-1"}\n: 中间注释\n\n');

    expect(events).toEqual([{ id: null, event: "message", data: { id: "job-1" } }]);
  });

  it("畸形 JSON 帧丢弃后继续派发后续帧", () => {
    const events = parseAll('data: not-json\n\ndata: {"ok":true}\n\n');

    expect(events).toEqual([{ id: null, event: "message", data: { ok: true } }]);
  });

  it("data 多行按换行连接，拼接后非法 JSON 的帧被丢弃", () => {
    const events = parseAll(
      'data: {"season": 20\ndata: 25}\n\ndata: {"name":\ndata: "高压逼抢"}\n\n',
    );

    expect(events).toEqual([{ id: null, event: "message", data: { name: "高压逼抢" } }]);
  });

  it("非对象负载整帧丢弃", () => {
    const events = parseAll(
      'data: 42\n\ndata: "text"\n\ndata: [1,2]\n\ndata: null\n\ndata: {"ok":true}\n\n',
    );

    expect(events).toEqual([{ id: null, event: "message", data: { ok: true } }]);
  });

  it("缺省 event 为 message 且缺省 id 为 null", () => {
    const events = parseAll('data: {}\n\n');

    expect(events).toEqual([{ id: null, event: "message", data: {} }]);
  });

  it("空 data 不派发", () => {
    const events = parseAll('id: 3\nevent: ready\ndata:\n\n');

    expect(events).toEqual([]);
  });

  it("连续空行不产生额外事件", () => {
    const events = parseAll('data: {"a":1}\n\n\n\ndata: {"a":2}\n\n');

    expect(events).toEqual([
      { id: null, event: "message", data: { a: 1 } },
      { id: null, event: "message", data: { a: 2 } },
    ]);
  });

  it("值保留内部冒号且剥掉单个前导空格", () => {
    const events = parseAll('event: job.updated\ndata: {"u":"a:b"}\n\n');

    expect(events).toEqual([{ id: null, event: "job.updated", data: { u: "a:b" } }]);
  });

  it("双空格字段只剥一个前导空格", () => {
    const events = parseAll('event:  job.updated\ndata: {"id":"job-1"}\n\n');

    expect(events).toEqual([{ id: null, event: " job.updated", data: { id: "job-1" } }]);
  });

  it("remainder 保留已读取但未完成帧的原始文本", () => {
    const { remainder, events } = frameOf('data: {"a":1}\n\nid: 9\nevent: job.updated\n');

    expect(events).toEqual([{ id: null, event: "message", data: { a: 1 } }]);
    expect(remainder).toBe("id: 9\nevent: job.updated\n");
  });
});

describe("connectEvents", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("请求事件流地址并携带鉴权头且首次不带 Last-Event-ID", async () => {
    const stream = controlledStream();
    const { fetchImpl, calls } = recordingFetch([() => stream.response]);
    const { events, onEvent } = collect();
    const subscription = connectEvents(connection, { onEvent }, { fetchImpl });

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe("http://127.0.0.1:43210/api/events");
    const headers = headersOf(calls[0]);
    expect(headers.get("Authorization")).toBe("Bearer test-token");
    expect(headers.get("Accept")).toBe("text/event-stream");
    expect(headers.get("Last-Event-ID")).toBeNull();
    expect(events).toEqual([]);

    subscription.stop();
  });

  it("收到事件后回调并报告 connecting 与 open", async () => {
    const stream = controlledStream();
    const { fetchImpl } = recordingFetch([() => stream.response]);
    const { events, onEvent } = collect();
    const { statuses, onStatus } = statusRecorder();
    const subscription = connectEvents(connection, { onEvent, onStatus }, { fetchImpl });

    stream.send('id: 1\nevent: job.updated\ndata: {"id":"job-1"}\n\n');

    await vi.waitFor(() => expect(events).toHaveLength(1));
    expect(events[0]).toEqual({ id: "1", event: "job.updated", data: { id: "job-1" } });
    expect(statuses.slice(0, 2)).toEqual(["connecting", "open"]);

    subscription.stop();
  });

  it("重连请求携带最后收到的事件 id 而首次不带", async () => {
    const first = controlledStream();
    const second = controlledStream();
    const { fetchImpl, calls } = recordingFetch([
      () => first.response,
      () => second.response,
      () => openResponse(),
    ]);
    const { onEvent } = collect();
    const subscription = connectEvents(
      connection,
      { onEvent },
      { fetchImpl, baseDelayMs: 5, maxDelayMs: 20 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    first.send('id: 7\nevent: job.updated\ndata: {"id":"job-1"}\n\n');
    first.close();

    await vi.waitFor(() => expect(calls).toHaveLength(2));
    expect(headersOf(calls[0]).get("Last-Event-ID")).toBeNull();
    expect(headersOf(calls[1]).get("Last-Event-ID")).toBe("7");

    second.send('id: 9\nevent: job.updated\ndata: {"id":"job-1"}\n\n');
    second.close();
    await vi.waitFor(() => expect(calls).toHaveLength(3));
    expect(headersOf(calls[2]).get("Last-Event-ID")).toBe("9");

    subscription.stop();
  });

  it("非 2xx 响应进入重连", async () => {
    const { fetchImpl, calls } = recordingFetch([
      () => new Response("", { status: 500 }),
      () => openResponse(),
    ]);
    const { onEvent } = collect();
    const { statuses, onStatus } = statusRecorder();
    const subscription = connectEvents(
      connection,
      { onEvent, onStatus },
      { fetchImpl, baseDelayMs: 5, maxDelayMs: 20 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(2));
    expect(statuses).toContain("reconnecting");

    subscription.stop();
  });

  it("响应缺少 body 时进入重连", async () => {
    const { fetchImpl, calls } = recordingFetch([
      () => new Response(null),
      () => openResponse(),
    ]);
    const { onEvent } = collect();
    const subscription = connectEvents(
      connection,
      { onEvent },
      { fetchImpl, baseDelayMs: 5, maxDelayMs: 20 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(2));

    subscription.stop();
  });

  it("流读取错误后进入重连", async () => {
    const broken = controlledStream();
    const { fetchImpl, calls } = recordingFetch([
      () => broken.response,
      () => openResponse(),
    ]);
    const { onEvent } = collect();
    const subscription = connectEvents(
      connection,
      { onEvent },
      { fetchImpl, baseDelayMs: 5, maxDelayMs: 20 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    broken.fail();

    await vi.waitFor(() => expect(calls).toHaveLength(2));

    subscription.stop();
  });

  it("退避按倍数递增并在上限封顶", async () => {
    vi.useFakeTimers();
    const { fetchImpl, calls } = recordingFetch([() => new Response("", { status: 503 })]);
    const { onEvent } = collect();
    const subscription = connectEvents(
      connection,
      { onEvent },
      { fetchImpl, baseDelayMs: 10, maxDelayMs: 25 },
    );

    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(9);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(2);

    await vi.advanceTimersByTimeAsync(19);
    expect(calls).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(3);

    await vi.advanceTimersByTimeAsync(24);
    expect(calls).toHaveLength(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(4);

    await vi.advanceTimersByTimeAsync(25);
    expect(calls).toHaveLength(5);

    subscription.stop();
  });

  it("连接成功后退避重置为基础间隔", async () => {
    vi.useFakeTimers();
    const opened = controlledStream();
    const { fetchImpl, calls } = recordingFetch([
      () => new Response("", { status: 503 }),
      () => opened.response,
      () => openResponse(),
    ]);
    const { onEvent } = collect();
    const subscription = connectEvents(
      connection,
      { onEvent },
      { fetchImpl, baseDelayMs: 10, maxDelayMs: 40 },
    );

    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(10);
    expect(calls).toHaveLength(2);

    opened.close();
    await vi.advanceTimersByTimeAsync(10);
    expect(calls).toHaveLength(3);

    subscription.stop();
  });

  it("stop 清除定时器、中止请求并报告 closed", async () => {
    vi.useFakeTimers();
    const { fetchImpl, calls } = recordingFetch([() => new Response("", { status: 503 })]);
    const { onEvent } = collect();
    const { statuses, onStatus } = statusRecorder();
    const subscription = connectEvents(
      connection,
      { onEvent, onStatus },
      { fetchImpl, baseDelayMs: 10, maxDelayMs: 20 },
    );

    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);
    const signal = calls[0].init.signal;
    expect(signal?.aborted).toBe(false);

    subscription.stop();
    expect(signal?.aborted).toBe(true);
    expect(statuses.at(-1)).toBe("closed");

    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toHaveLength(1);
  });

  it("stop 幂等：重复调用只报告一次 closed 且不再重连", async () => {
    vi.useFakeTimers();
    const { fetchImpl, calls } = recordingFetch([() => new Response("", { status: 503 })]);
    const { onEvent } = collect();
    const { statuses, onStatus } = statusRecorder();
    const subscription = connectEvents(
      connection,
      { onEvent, onStatus },
      { fetchImpl, baseDelayMs: 10, maxDelayMs: 20 },
    );

    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);
    const signal = calls[0].init.signal;
    let aborts = 0;
    signal?.addEventListener("abort", () => {
      aborts += 1;
    });

    subscription.stop();
    subscription.stop();

    expect(aborts).toBe(1);
    expect(signal?.aborted).toBe(true);
    expect(statuses.filter((status) => status === "closed")).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);

    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toHaveLength(1);
  });

  it("stop 后活动流结束不再重连", async () => {
    const stream = controlledStream();
    const { fetchImpl, calls } = recordingFetch([() => stream.response]);
    const { onEvent } = collect();
    const subscription = connectEvents(
      connection,
      { onEvent },
      { fetchImpl, baseDelayMs: 5, maxDelayMs: 20 },
    );

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    subscription.stop();
    stream.close();

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(calls).toHaveLength(1);
  });

  it("跨字节 UTF-8 分块用流式解码还原中文", async () => {
    const stream = controlledStream();
    const { fetchImpl } = recordingFetch([() => stream.response]);
    const { events, onEvent } = collect();
    const subscription = connectEvents(connection, { onEvent }, { fetchImpl });

    const bytes = new TextEncoder().encode('data: {"name":"高压逼抢"}\n\n');
    const cut = 16;
    stream.sendBytes(bytes.slice(0, cut));
    stream.sendBytes(bytes.slice(cut));

    await vi.waitFor(() => expect(events).toHaveLength(1));
    expect(events[0].data).toEqual({ name: "高压逼抢" });

    subscription.stop();
  });
});
