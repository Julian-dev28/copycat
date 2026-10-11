"use client";

import { useEffect, useRef, useState } from "react";
import { openEventStream } from "@/lib/api/eventsStream";
import type { EngineEvent } from "@/lib/api/types";
import { useAuth } from "@/context/AuthContext";

const MAX_BUFFERED_EVENTS = 300;

export type StreamConnectionState = "idle" | "connecting" | "open" | "error";

/** Live event feed, newest first, capped at MAX_BUFFERED_EVENTS in memory. */
export function useEventStream() {
  const { hasToken, token } = useAuth();
  const [events, setEvents] = useState<EngineEvent[]>([]);
  const [conn, setConn] = useState<StreamConnectionState>("connecting");
  const [connKey, setConnKey] = useState(token);
  // A new token means a new connection: back to "connecting", adjusted during render.
  if (connKey !== token) {
    setConnKey(token);
    setConn("connecting");
  }
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!hasToken) return;
    seenRef.current = new Set();

    const close = openEventStream({
      onOpen: () => setConn("open"),
      onEvent: (event) => {
        const key = `${event.ts_ms}:${event.action}:${event.leader ?? ""}:${event.coin ?? ""}`;
        if (seenRef.current.has(key)) return;
        seenRef.current.add(key);
        setEvents((prev) => [event, ...prev].slice(0, MAX_BUFFERED_EVENTS));
      },
      onError: () => setConn("error"),
      onUnauthorized: () => setConn("error"),
    });

    return close;
  }, [hasToken, token]);

  return { events, state: hasToken ? conn : ("idle" as StreamConnectionState) };
}
