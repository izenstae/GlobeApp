import { useStore } from "../store";

/** An empty globe says which feeds are connected and when each last returned
 * data. Nothing is invented to make the UI look populated. */
export default function EmptyState() {
  const feeds = useStore((s) => s.feeds);
  const events = useStore((s) => s.events);
  if (events.size > 0) return null;
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
      <div className="pointer-events-auto max-w-md border border-edge bg-panel/95 p-4 text-sm">
        <div className="text-bone">No events ingested yet.</div>
        <div className="mt-2 space-y-1 font-mono text-xs text-muted">
          {feeds.length === 0 && (
            <p>
              No feeds have run. Start the backend scheduler, and register
              credentials with{" "}
              <code className="text-bone">python -m app.auth.cli setup</code> for
              ACLED and FIRMS. GDELT needs no key and ingests on its own within
              15 minutes.
            </p>
          )}
          {feeds.map((feed) => (
            <p key={feed.source}>
              {feed.source}:{" "}
              {feed.last_success_at
                ? `last returned data ${feed.last_success_at}`
                : feed.last_error
                  ? `failing — ${feed.last_error.slice(0, 120)}`
                  : "has not returned data yet"}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}
