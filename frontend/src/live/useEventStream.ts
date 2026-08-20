import { useEffect, useRef } from "react";
import { STREAM_URL } from "../api";
import { passesServerFilters, useStore } from "../store";
import type { EventFull } from "../types";
import { EventQueue } from "./EventQueue";

/** SSE subscription. EventSource reconnects for free; connection state is
 * surfaced in the status bar rather than hidden. */
export function useEventStream(queue: EventQueue): void {
  const upsertLive = useStore((s) => s.upsertLive);
  const setStreamConnected = useStore((s) => s.setStreamConnected);
  const setQueueDepth = useStore((s) => s.setQueueDepth);
  const queueRef = useRef(queue);
  queueRef.current = queue;

  useEffect(() => {
    const source = new EventSource(STREAM_URL);
    source.onopen = () => setStreamConnected(true);
    source.onerror = () => setStreamConnected(false);
    source.addEventListener("conflict_event", (message: MessageEvent<string>) => {
      let event: EventFull;
      try {
        event = JSON.parse(message.data) as EventFull;
      } catch {
        return;
      }
      // Events excluded by the active server-side filters neither plot nor
      // fly the camera; they arrive again on the next filtered refetch if the
      // filter changes.
      if (!passesServerFilters(useStore.getState(), event)) return;
      upsertLive(event);
      queueRef.current.enqueue(event);
    });
    const unsubscribe = queue.onChange(() => setQueueDepth(queue.depth));
    return () => {
      unsubscribe();
      source.close();
    };
  }, [queue, upsertLive, setStreamConnected, setQueueDepth]);
}
