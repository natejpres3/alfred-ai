export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message ?? `Request failed (${status})`);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(path.startsWith("/api") ? path : `/api${path}`, {
    credentials: "same-origin",
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : init.body,
    ...rest,
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* not json */
    }
    if (res.status === 401 && typeof window !== "undefined" && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/register")) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

/** POST that returns a Server-Sent Events stream (used by the tutor). Calls onDelta for each text chunk. */
export async function streamSSE(path: string, body: unknown, onDelta: (text: string) => void, signal?: AbortSignal) {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() ?? "";
    for (const evt of events) {
      const lines = evt.split(/\r?\n/);
      const type = lines.find((l) => l.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
      if (type === "delta" && data) onDelta(JSON.parse(data).text as string);
    }
  }
}
