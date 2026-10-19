import { PLANTS, FEED_LEVEL_LABEL, type Risk } from "@/lib/ct/data";

/** Live feed facts for one plant, shaped by the overview feature. */
export interface FeedView {
  pending: boolean;
  error: boolean;
  level: Risk | null;
  wavescanCars: number | null;
  filmCars: number | null;
  files: { key: string; domain: string; name: string; status: string; since: string }[];
}

const LEVEL_VAR: Record<string, string> = {
  nominal: "var(--nominal)",
  caution: "var(--caution)",
  critical: "var(--critical)",
};

interface Props {
  /** Plant ids whose data-feed switch is currently on. */
  active: string[];
  onToggle: (plantId: string) => void;
  onReset: () => void;
  feeds: Record<string, FeedView>;
  /** Reports that open over the map (Overview IMG, IMG Color). */
  reports: {
    key: string;
    label: string;
    description: string;
    open: boolean;
    onOpen: () => void;
    trigger: React.Ref<HTMLButtonElement>;
  }[];
}

/**
 * Overview Status — one switch per plant data feed. Opening a switch
 * highlights that plant on the map and expands its feed detail inline;
 * closing collapses it. Status colours come from this month's weekly upload plan.
 */
export function Simulator({ active, onToggle, onReset, feeds, reports }: Props) {
  return (
    <div className="panel flex h-full flex-col">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">Regional reports &amp; feeds</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Open a report or expand a plant’s upload details.
          </p>
        </div>
        <button
          onClick={onReset}
          disabled={active.length === 0}
          className="min-h-11 shrink-0 rounded-sm border border-border px-3 py-2 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-35"
        >
          Reset
        </button>
      </header>

      <div className="grid gap-2 p-3">
        {reports.map((r) => (
          <button
            key={r.key}
            ref={r.trigger}
            type="button"
            onClick={r.onOpen}
            aria-haspopup="dialog"
            aria-expanded={r.open}
            className="group flex w-full items-center gap-3 rounded-sm border px-3 py-2.5 text-left transition-colors hover:border-primary"
            style={{
              borderColor: r.open ? "var(--signal)" : "var(--border)",
              backgroundColor: r.open ? "var(--surface-2)" : "transparent",
            }}
          >
            <svg
              viewBox="0 0 16 16"
              aria-hidden="true"
              className="size-4 shrink-0"
              fill="none"
              stroke="var(--signal)"
              strokeWidth="1.5"
            >
              <path d="M2 14h12M4 12V7M8 12V3M12 12V9" strokeLinecap="round" />
            </svg>
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-semibold leading-snug">{r.label}</span>
              <span className="mt-1 block text-xs leading-snug text-muted-foreground">
                {r.description}
              </span>
            </span>
            <span className="num shrink-0 rounded-sm border border-border px-1.5 py-0.5 text-[9px] uppercase tracking-widest text-muted-foreground">
              report
            </span>
          </button>
        ))}
        {PLANTS.map((p) => {
          const on = active.includes(p.id);
          const feed = feeds[p.code];
          const c = feed?.level ? LEVEL_VAR[feed.level] : "var(--muted-foreground)";
          const summary = [
            { label: "Wave scan records", count: feed?.wavescanCars },
            { label: "Film thickness", count: feed?.filmCars },
          ];
          return (
            <div
              key={p.id}
              className="rounded-sm border transition-all duration-300"
              style={{
                borderColor: on ? c : "var(--border)",
                backgroundColor: on ? "var(--surface-2)" : "transparent",
              }}
            >
              <button
                onClick={() => onToggle(p.id)}
                aria-pressed={on}
                aria-expanded={on}
                className="group flex w-full items-center gap-3 px-3 py-2.5 text-left"
              >
                {/* physical rocker switch */}
                <span
                  className="relative flex h-7 w-4 shrink-0 items-start rounded-[3px] border p-0.5 transition-colors"
                  style={{
                    borderColor: on ? c : "var(--border)",
                    backgroundColor: "var(--switch-well)",
                  }}
                >
                  <span
                    className="block h-3 w-full rounded-[2px] transition-transform duration-300 ease-out"
                    style={{
                      backgroundColor: on ? c : "var(--input)",
                      transform: on ? "translateY(12px)" : "translateY(0)",
                    }}
                  />
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className="block text-xs font-semibold leading-snug transition-colors"
                    style={{ color: on ? c : "var(--foreground)" }}
                  >
                    {p.code}
                  </span>
                  <span className="mt-1 block text-xs leading-snug text-muted-foreground">
                    Data Feed
                  </span>
                </span>
                {/* live status chip — same colour story as the map dot */}
                <span
                  className="num shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-widest transition-colors"
                  style={{
                    borderColor: on ? c : "var(--border)",
                    color: on ? c : "var(--muted-foreground)",
                  }}
                >
                  {feed?.level
                    ? FEED_LEVEL_LABEL[feed.level]
                    : feed?.pending
                      ? "Checking…"
                      : feed?.error
                        ? "Unavailable"
                        : "No plan"}
                </span>
              </button>

              {/* expandable feed detail — only while the switch is on */}
              <div
                inert={!on}
                aria-hidden={!on}
                className="grid transition-[grid-template-rows] duration-300 ease-out"
                style={{ gridTemplateRows: on ? "1fr" : "0fr" }}
              >
                <div className="overflow-hidden">
                  {feed && (
                    <div className="border-t border-border px-3 pb-3 pt-2">
                      {/* summary trio — the old order-book shape, per plant */}
                      <div className="flex items-center justify-between">
                        <p className="eyebrow">feed summary</p>
                        <p className="num text-[10px] text-muted-foreground">{p.name}</p>
                      </div>
                      <ul className="mt-1.5 space-y-1">
                        {summary.map((row) => (
                          <li key={row.label} className="flex items-center gap-2 text-[11px]">
                            <span className="flex-1">{row.label}</span>
                            <span className="num w-10 text-right text-muted-foreground">
                              {row.count ?? "—"}
                            </span>
                            <span className="num w-16 text-right tabular-nums text-muted-foreground">
                              cars
                            </span>
                          </li>
                        ))}
                      </ul>

                      {/* feed list — the old stockout-list shape, per plant */}
                      <div className="mt-2.5 flex items-center justify-between border-t border-border pt-2">
                        <p className="eyebrow">feeds</p>
                        <p className="num text-[10px] text-muted-foreground">latest uploads</p>
                      </div>
                      <ul className="mt-1.5 space-y-px">
                        {feed.files.length === 0 && (
                          <li className="px-1 py-1.5 text-[11px] text-muted-foreground">
                            {feed.pending
                              ? "Loading uploads…"
                              : feed.error
                                ? "Uploads unavailable · retry above"
                                : "No files uploaded yet"}
                          </li>
                        )}
                        {feed.files.map((f, i) => (
                          <li
                            key={f.key}
                            className="flex items-center gap-2.5 rounded-sm px-1 py-1.5"
                            style={{ animation: `ct-rise .4s ease-out ${i * 0.05}s both` }}
                          >
                            <span
                              className="size-1.5 shrink-0 rounded-full"
                              style={{
                                backgroundColor:
                                  f.status === "COMMITTED" ? "var(--nominal)" : "var(--caution)",
                              }}
                            />
                            <span className="num w-6 shrink-0 text-[10px] text-muted-foreground">
                              {f.domain}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[11px]" title={f.name}>
                              {f.name}
                            </span>
                            <span className="num text-[10px] lowercase text-muted-foreground">
                              {f.status}
                            </span>
                            <span className="num w-12 shrink-0 text-right text-[11px] font-semibold tabular-nums">
                              {f.since}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
