/**
 * Live event feed: GET /api/events/stream (SSE). Native EventSource can't
 * set an Authorization header, and the api requires a bearer token on every
 * route, so we use @microsoft/fetch-event-source (fetch-based, supports
 * headers + automatic reconnect with backoff) instead of hand-rolling
 * reconnect/backoff over a raw ReadableStream.
 *
 * NOTE for the api service: this connects browser -> api directly (the
 * token lives in the browser's localStorage, never on a web server), so
 * the api must send CORS headers for the web app's origin, including on
 * the SSE route, with `Authorization` in Access-Control-Allow-Headers.
 */
import { fetchEventSource, type EventSourceMessage } from "@microsoft/fetch-event-source";
import { getApiBase } from "./client";
import { getStoredToken } from "./token";
import type { EngineEvent } from "./types";

export interface EventStreamHandlers {
  onEvent: (event: EngineEvent) => void;
  onOpen?: () => void;
  /** Called on any error/retry. `fatal: true` means fetch-event-source gave up. */
  onError?: (error: unknown, fatal: boolean) => void;
  onUnauthorized?: () => void;
}

/**
 * Opens the stream and returns an abort function. Caller (useEventStream)
 * owns the AbortController lifecycle so React effect cleanup can cancel it.
 */
export function openEventStream(handlers: EventStreamHandlers): () => void {
  const controller = new AbortController();
  const token = getStoredToken();

  fetchEventSource(`${getApiBase()}/api/events/stream`, {
    signal: controller.signal,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    openWhenHidden: true,
    async onopen(response) {
      if (response.status === 401) {
        handlers.onUnauthorized?.();
        throw new Error("unauthorized");
      }
      handlers.onOpen?.();
    },
    onmessage(msg: EventSourceMessage) {
      if (!msg.data) return;
      try {
        const parsed = JSON.parse(msg.data) as EngineEvent;
        handlers.onEvent(parsed);
      } catch (err) {
        handlers.onError?.(err, false);
      }
    },
    onerror(err) {
      handlers.onError?.(err, false);
      // returning undefined (default) tells fetch-event-source to keep
      // retrying with its built-in backoff; we only stop on unmount via
      // controller.abort() below.
    },
  }).catch((err: unknown) => {
    if (controller.signal.aborted) return;
    handlers.onError?.(err, true);
  });

  return () => controller.abort();
}
