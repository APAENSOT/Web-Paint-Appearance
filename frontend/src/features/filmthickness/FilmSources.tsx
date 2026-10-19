import { useEffect, useState } from "react";
import { SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import {
  layers,
  retainedRules,
  resolveRow,
  type FilmStandardsOut,
  type Layer,
  type Resolved,
} from "./film-standards";
function Attribution({ orientation, resolved }: { orientation: string; resolved: Resolved }) {
  const rule = resolved.rule;
  return (
    <section
      aria-label={`${orientation} source`}
      className="min-w-0 space-y-3 rounded border border-border bg-[var(--surface-2)] p-4"
    >
      <h3 className="font-semibold">{orientation}</h3>
      {rule ? (
        <>
          {resolved.inherited && (
            <p className="text-sm font-medium">Plant-wide source (Inherited)</p>
          )}
          <dl className="space-y-4 break-words text-sm">
            <div>
              <dt className="text-muted-foreground">Document reference</dt>
              <dd className="mt-1">{rule.source_document ?? "Not provided"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Source note</dt>
              <dd className="mt-1 whitespace-pre-wrap">{rule.source_note}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Published (Asia/Bangkok)</dt>
              <dd className="mt-1">
                <time dateTime={rule.created_at}>
                  {new Intl.DateTimeFormat("en-GB", {
                    timeZone: "Asia/Bangkok",
                    dateStyle: "medium",
                    timeStyle: "medium",
                  }).format(new Date(rule.created_at))}
                </time>
              </dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No source available</p>
      )}
    </section>
  );
}
export function FilmSources({ data }: { data: FilmStandardsOut }) {
  const [layer, setLayer] = useState<Layer>("ECOAT");
  const [color, setColor] = useState<string | null>(null);
  const offered = [...data.colors].sort((a, b) => a.color_name.localeCompare(b.color_name));
  const retained = retainedRules(data, layer);
  const valid =
    color === null ||
    offered.some((c) => c.color_name === color) ||
    retained.some((r) => r.color_name === color);
  const selected = valid ? color : null;
  useEffect(() => {
    if (!valid) setColor(null);
  }, [valid]);
  const resolved = resolveRow(
    data,
    layer,
    selected,
    selected !== null && !offered.some((c) => c.color_name === selected),
  );
  // Encode the selector values so an exact colour name can never collide with Plant-wide.
  const selectValue = (name: string | null) => JSON.stringify(name);
  return (
    <SheetContent
      side="right"
      className="flex w-full max-w-[100vw] flex-col gap-0 overflow-hidden p-0 sm:max-w-[100vw] md:w-[480px] md:max-w-[480px] [&>button]:grid [&>button]:min-h-11 [&>button]:min-w-11 [&>button]:place-items-center motion-reduce:animate-none motion-reduce:transition-none"
    >
      <header className="border-b border-border p-5 pr-16">
        <SheetTitle>Sources</SheetTitle>
        <SheetDescription className="mt-2">
          {data.plant_code} Film Thickness · Latest published rule provenance.
        </SheetDescription>
      </header>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        <div className="grid gap-4">
          <label className="text-sm font-medium">
            Layer
            <select
              aria-label="Layer"
              className="mt-2 min-h-11 w-full rounded border border-border bg-background px-3"
              value={layer}
              onChange={(e) => {
                setLayer(e.target.value as Layer);
                setColor(null);
              }}
            >
              {layers.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm font-medium">
            Rule
            <select
              aria-label="Rule"
              className="mt-2 min-h-11 w-full rounded border border-border bg-background px-3"
              value={selectValue(selected)}
              onChange={(e) => setColor(JSON.parse(e.target.value) as string | null)}
            >
              <option value={selectValue(null)}>Plant-wide</option>
              {offered.map((c) => (
                <option key={c.color_name} value={selectValue(c.color_name)}>
                  {c.color_name}
                </option>
              ))}
              {retained.map((r) => (
                <option key={r.color_name} value={selectValue(r.color_name)}>
                  {r.color_name} — Not offered
                </option>
              ))}
            </select>
          </label>
        </div>
        <Attribution orientation="Horizontal" resolved={resolved.h} />
        <Attribution orientation="Vertical" resolved={resolved.v} />
      </div>
    </SheetContent>
  );
}
