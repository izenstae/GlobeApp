import { useStore } from "../store";
import type { FeedHealth } from "../types";

/** Bottom bar: live/pause state with visible auto-resume countdown, pending
 * queue badge, per-feed health, and the mandatory ACLED attribution. Errors
 * are specific and actionable, never vague. */

function feedLabel(feed: FeedHealth): { text: string; bad: boolean } {
  if (feed.credential_status === "dead") {
    return {
      text: `${feed.source}: credential dead — run \`python -m app.auth.cli setup --provider ${feed.source}\``,
      bad: true,
    };
  }
  if (feed.credential_status === "degraded") {
    return { text: `${feed.source}: auth degraded, retrying`, bad: true };
  }
  if (feed.last_error) {
    return { text: `${feed.source}: ${feed.consecutive_failures} failed — ${truncate(feed.last_error, 80)}`, bad: true };
  }
  if (feed.last_success_at) {
    return { text: `${feed.source}: ok ${timeAgo(feed.last_success_at)}`, bad: false };
  }
  return { text: `${feed.source}: no data yet`, bad: false };
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - Date.parse(iso)) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

export default function StatusBar({
  onResume,
  onToggleQueue,
}: {
  onResume: () => void;
  onToggleQueue: () => void;
}) {
  const liveMode = useStore((s) => s.liveMode);
  const resumeAt = useStore((s) => s.resumeAt);
  const queueDepth = useStore((s) => s.queueDepth);
  const feeds = useStore((s) => s.feeds);
  const streamConnected = useStore((s) => s.streamConnected);
  const showHotspots = useStore((s) => s.showHotspots);
  const toggleHotspots = useStore((s) => s.toggleHotspots);
  const showArcs = useStore((s) => s.showArcs);
  const toggleArcs = useStore((s) => s.toggleArcs);

  const countdown =
    resumeAt !== null ? Math.max(0, Math.ceil((resumeAt - Date.now()) / 1000)) : null;

  return (
    <footer className="pointer-events-auto absolute inset-x-0 bottom-0 z-30 border-t border-edge bg-panel/95 px-4 py-2 font-mono text-xs">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              liveMode === "live"
                ? streamConnected
                  ? "bg-signal"
                  : "bg-faint"
                : "bg-muted"
            }`}
            aria-hidden
          />
          {liveMode === "live" ? (
            <span className="text-bone">
              LIVE{streamConnected ? "" : " · stream reconnecting"}
            </span>
          ) : (
            <span className="text-bone">
              Live paused, {queueDepth} event{queueDepth === 1 ? "" : "s"} waiting
              <button
                onClick={onResume}
                className="ml-2 border border-signal px-2 py-0.5 text-signal hover:bg-signal hover:text-base focus:outline-none focus:ring-1 focus:ring-signal"
              >
                resume{countdown !== null ? ` (${countdown}s)` : ""}
              </button>
            </span>
          )}
        </div>

        <button
          onClick={onToggleQueue}
          className="text-muted hover:text-bone focus:outline-none focus:ring-1 focus:ring-signal"
          aria-label={`Pending event queue, ${queueDepth} events`}
        >
          queue <span className="text-bone">{queueDepth}</span>
        </button>

        <button
          onClick={toggleHotspots}
          className={`focus:outline-none focus:ring-1 focus:ring-signal ${
            showHotspots ? "text-bone" : "text-muted hover:text-bone"
          }`}
          aria-pressed={showHotspots}
        >
          thermal overlay {showHotspots ? "on" : "off"}
        </button>

        <button
          onClick={toggleArcs}
          className={`focus:outline-none focus:ring-1 focus:ring-signal ${
            showArcs ? "text-bone" : "text-muted hover:text-bone"
          }`}
          aria-pressed={showArcs}
          title="Cross-border strike arcs; origins are country-level inferences from actor attribution"
        >
          strike arcs {showArcs ? "on" : "off"}
        </button>

        <div className="flex flex-wrap items-center gap-x-4">
          {feeds.length === 0 ? (
            <span className="text-muted">no feeds configured</span>
          ) : (
            feeds.map((feed) => {
              const { text, bad } = feedLabel(feed);
              return (
                <span key={feed.source} className={bad ? "text-signal" : "text-muted"}>
                  {text}
                </span>
              );
            })
          )}
        </div>

        <span className="ml-auto text-faint">
          Conflict data ©{" "}
          <a
            href="https://acleddata.com"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-muted"
          >
            ACLED
          </a>
          , used per their Terms of Use · GDELT · NASA FIRMS
        </span>
      </div>
    </footer>
  );
}
