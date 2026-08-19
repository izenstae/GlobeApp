import type { EventQueue } from "../live/EventQueue";
import { useStore } from "../store";

export default function QueueList({
  queue,
  onJumpTo,
}: {
  queue: EventQueue;
  onJumpTo: (eventId: number) => void;
}) {
  const queueOpen = useStore((s) => s.queueOpen);
  const setQueueOpen = useStore((s) => s.setQueueOpen);
  if (!queueOpen) return null;
  const items = queue.list();
  return (
    <div
      className="pointer-events-auto absolute bottom-12 left-4 z-30 max-h-72 w-96 overflow-y-auto border border-edge bg-panel/95 p-2"
      role="listbox"
      aria-label="Pending events"
    >
      <div className="mb-1 flex items-center justify-between font-mono text-xs text-faint">
        <span>pending events ({items.length})</span>
        <button
          onClick={() => setQueueOpen(false)}
          className="px-1 text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
          aria-label="Close queue"
        >
          ✕
        </button>
      </div>
      {items.length === 0 && <div className="p-2 font-mono text-xs text-muted">queue empty</div>}
      <ul>
        {items.map(({ event, priority }) => (
          <li key={event.id}>
            <button
              onClick={() => onJumpTo(event.id)}
              className="w-full px-1 py-1 text-left text-xs text-muted hover:bg-edge hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
            >
              <span className="font-mono text-faint">{priority.toFixed(2)}</span>{" "}
              <span className="text-bone">{event.category}</span>{" "}
              {event.location_name ?? event.country ?? "unknown location"}
              {event.fatalities ? ` · ${event.fatalities} killed` : ""}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
