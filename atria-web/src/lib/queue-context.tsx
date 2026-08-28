"use client";

/**
 * One websocket for the whole app, broadcast through context.
 *
 * The queue is server state, not client state. Treating it as client state is
 * what produces boards that disagree with the engine, so nothing here mutates a
 * snapshot — actions post to the API and the next frame arrives over the socket.
 */
import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from "react";
import { api } from "@/lib/api";
import type { Snapshot } from "@/types/atria";

type Status = "connecting" | "live" | "reconnecting";

interface QueueValue {
  snapshot: Snapshot | null;
  status: Status;
  refresh: () => Promise<void>;
}

const QueueContext = createContext<QueueValue>({
  snapshot: null,
  status: "connecting",
  refresh: async () => {},
});

export const useQueue = () => useContext(QueueContext);

export function QueueProvider({ children }: { children: React.ReactNode }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const socket = useRef<WebSocket | null>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSnapshot(await api.queue());
    } catch {
      /* the socket is the primary channel; a failed poll is not fatal */
    }
  }, []);

  useEffect(() => {
    let closed = false;

    const connect = () => {
      const ws = new WebSocket(api.wsUrl());
      socket.current = ws;

      ws.onopen = () => setStatus("live");
      ws.onmessage = (e) => {
        try {
          setSnapshot(JSON.parse(e.data) as Snapshot);
        } catch {
          /* ignore a malformed frame rather than tearing down the board */
        }
      };
      // Reconnect rather than going dark. A blank board during a shift is worse
      // than a stale one, and the next frame is at most a couple of seconds away.
      ws.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        retry.current = setTimeout(connect, 1200);
      };
      ws.onerror = () => ws.close();
    };

    refresh();
    connect();
    return () => {
      closed = true;
      if (retry.current) clearTimeout(retry.current);
      socket.current?.close();
    };
  }, [refresh]);

  return (
    <QueueContext.Provider value={{ snapshot, status, refresh }}>
      {children}
    </QueueContext.Provider>
  );
}
