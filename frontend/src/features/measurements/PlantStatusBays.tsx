import { FEED_LEVEL_LABEL } from "@/lib/ct/data";
import { sinceText, usePlantFeeds, type PlantFeed } from "@/features/overview/plant-feed";

/** One plant's slice of GET /landing/status: the same facts the landing card shows. */
function usePlant(code: string): PlantFeed | undefined {
  return usePlantFeeds()[code];
}

/** The feed remains visible when the compact status panel is collapsed. */
export function CompactFeedStatus({ code }: { code: string }) {
  const feed = usePlant(code);
  const status = feed?.status;
  return (
    <span
      className="block text-xs"
      style={{ color: status ? `var(--${status.level})` : "var(--muted-foreground)" }}
    >
      {feed?.pending
        ? "Checking feed…"
        : feed?.error
          ? "Feed unavailable"
          : status
            ? `Feed: ${FEED_LEVEL_LABEL[status.level]}`
            : "No upload plan"}
    </span>
  );
}

function Waiting({ feed }: { feed: PlantFeed | undefined }) {
  return (
    <p className="text-xs text-muted-foreground">
      {!feed || feed.pending ? "Loading…" : "Status unavailable · API error"}
    </p>
  );
}

/** This month's weekly upload plan: Update / Late / Missing. */
export function FeedFact({ code }: { code: string }) {
  const feed = usePlant(code);
  if (!feed || feed.pending || feed.error) return <Waiting feed={feed} />;
  const s = feed.status;
  if (!s)
    return <p className="text-xs text-muted-foreground">No standard models or colours set.</p>;
  return (
    <>
      <p className="text-sm font-bold" style={{ color: `var(--${s.level})` }}>
        {FEED_LEVEL_LABEL[s.level]}
        <span className="num ml-1.5 text-[11px] font-normal text-muted-foreground">
          week {s.week}
        </span>
      </p>
      <p className="num mt-0.5 text-[11px] text-muted-foreground">
        late {s.late} · missing {s.missing} · {s.pct.toFixed(1)}% of plan
      </p>
    </>
  );
}

/** The newest uploaded workbook and how long ago it arrived. */
export function UploadFact({ code }: { code: string }) {
  const feed = usePlant(code);
  if (!feed || feed.pending || feed.error) return <Waiting feed={feed} />;
  const last = feed.latest[0];
  if (!last) return <p className="text-sm font-bold">No uploads yet</p>;
  return (
    <>
      <p className="text-sm font-bold">
        {sinceText(last.started_at)} ago
        <span className="num ml-1.5 text-[11px] font-normal text-muted-foreground">
          {last.domain === "FILMTHICKNESS" ? "Film" : "Wave Scan"}
        </span>
      </p>
      <p className="mt-0.5 truncate text-[11px] text-muted-foreground" title={last.source_file}>
        {last.source_file}
      </p>
    </>
  );
}

/** Cars in the database for each domain, plus the month-to-date quality share. */
export function CarsFact({ code }: { code: string }) {
  const feed = usePlant(code);
  if (!feed || feed.pending || feed.error) return <Waiting feed={feed} />;
  return (
    <>
      <p className="num text-sm font-bold">
        {(feed.wavescanCars ?? 0).toLocaleString("en-US")}
        <span className="ml-1 text-[11px] font-normal text-muted-foreground">Wave Scan</span>
        <span className="px-2 text-muted-foreground">·</span>
        {(feed.filmCars ?? 0).toLocaleString("en-US")}
        <span className="ml-1 text-[11px] font-normal text-muted-foreground">Film</span>
      </p>
      <p className="num mt-0.5 text-[11px] text-muted-foreground">
        {feed.quality === null
          ? "No graded readings this month"
          : `Month-to-date quality ${feed.quality.toFixed(1)}%`}
      </p>
    </>
  );
}
