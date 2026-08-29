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

/**
 * How often the board is allowed to re-order itself.
 *
 * The engine emits a frame on every arrival and every set of readings, and
 * showing each one meant the list could reshuffle under a nurse mid-thought.
 * A settled cadence is easier to work against: you look up, the order has
 * changed once, and you can see what moved.
 *
 * This is presentation only. The engine still re-ranks continuously and the
 * audit records every change at the moment it happened — the board is just not
 * redrawn for each one.
 */
const REORDER_EVERY_MS = 20_000;

/**
 * What is too important to wait for the next beat.
 *
 * Anything that makes a patient MORE urgent goes on screen immediately. A
 * deterioration held back for up to twenty seconds to keep the list tidy would
 * be exactly the harm this system exists to prevent. Everything else — arrivals,
 * ordinary readings, waiting times ticking up — waits for the beat.
 */
function needsImmediateAttention(next: Snapshot, shown: Snapshot | null): boolean {
  if (!shown) return true;
  const before = new Map(shown.rows.map((r) => [r.ticket, r]));
  return next.rows.some((r) => {
    const was = before.get(r.ticket);
    if (!was) return false;                       // an arrival can wait
    if (r.band < was.band) return true;           // moved up: show it now
    if (r.state === "ESCALATED" && was.state !== "ESCALATED") return true;
    if (r.abstained && !was.abstained) return true;   // ATRIA gave up: a human is needed
    return false;
  });
}

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
  /** The newest frame from the engine, which may not be the one on screen. */
  const latest = useRef<Snapshot | null>(null);
  /** The frame currently drawn, so urgency is judged against what a nurse sees. */
  const shown = useRef<Snapshot | null>(null);

  const commit = useCallback((s: Snapshot) => {
    shown.current = s;
    setSnapshot(s);
  }, []);

  /** An action the nurse just took should be reflected at once, not on the beat. */
  const refresh = useCallback(async () => {
    try {
      const s = await api.queue();
      latest.current = s;
      commit(s);
    } catch {
      /* the socket is the primary channel; a failed poll is not fatal */
    }
  }, [commit]);

  // The beat. Anything urgent has already gone on screen by the time this runs.
  useEffect(() => {
    const beat = setInterval(() => {
      if (latest.current && latest.current !== shown.current) {
        commit(latest.current);
      }
    }, REORDER_EVERY_MS);
    return () => clearInterval(beat);
  }, [commit]);

  useEffect(() => {
    let closed = false;

    const connect = () => {
      const ws = new WebSocket(api.wsUrl());
      socket.current = ws;

      ws.onopen = () => setStatus("live");
      ws.onmessage = (e) => {
        try {
          const next = JSON.parse(e.data) as Snapshot;
          latest.current = next;
          // First frame, or somebody got worse: draw it now. Otherwise it waits
          // for the beat, so the list is not moving while a nurse reads it.
          if (needsImmediateAttention(next, shown.current)) commit(next);
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
      const ws = socket.current;
      if (!ws) return;
      // Closing a socket that is still shaking hands makes the browser log
      // "closed before the connection is established". It is harmless, and in
      // development React mounts every effect twice so it happens on every
      // load — which trains you to ignore console warnings, right up until one
      // of them matters. Wait for the handshake, then close.
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.onopen = () => ws.close();
      } else {
        ws.close();
      }
    };
  }, [refresh, commit]);

  return (
    <QueueContext.Provider value={{ snapshot, status, refresh }}>
      {children}
    </QueueContext.Provider>
  );
}
