/** Paired month values, with one explicit scale per unit and API-supplied change/verdict. */
import { evidenceCell as cell } from "../report-slides";
import type { AssistantAnswer } from "../report-types";

type Evidence = AssistantAnswer["evidence"];
const TOP = 5;

export function Shift({
  evidence,
  periods,
}: {
  evidence: Evidence;
  periods?: { before: string; now: string };
}) {
  const data = evidence.points
    .map((p, i) => ({
      ...p,
      before: cell(evidence.rows[i]?.[1] ?? null),
      now: cell(evidence.rows[i]?.[2] ?? null),
      change: cell(evidence.rows[i]?.[3] ?? null),
      verdict: cell(evidence.rows[i]?.[4] ?? null),
      unit: cell(evidence.rows[i]?.[3] ?? null)
        .replace(/^[-+−]?[\d.]+\s*/, "")
        .replace("—", ""),
    }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
    .slice(0, TOP);
  if (!data.length) return null;
  const units = [...new Set(data.map((p) => p.unit))];
  return (
    <div
      className="guide-shifts"
      role="img"
      aria-label={`Median before and now for the top ${data.length} boxes measured in both months: ${data.map((p) => `${p.label}, ${periods?.before ?? "earlier month"}: ${p.x} ${p.unit}, status ${p.before}; ${periods?.now ?? "later month"}: ${p.y} ${p.unit}, status ${p.now}; change ${p.change}, ${p.verdict}`).join("; ")}`}
    >
      <p className="mb-4 text-sm text-muted-foreground">
        Hollow dot: earlier month. Filled dot: later month. The labelled change and status explain
        whether the movement matters.
      </p>
      {units.map((unit) => {
        const group = data.filter((p) => p.unit === unit);
        const min = Math.min(...group.flatMap((p) => [p.x, p.y]));
        const max = Math.max(...group.flatMap((p) => [p.x, p.y]));
        const position = (value: number) =>
          max === min ? 50 : 5 + ((value - min) / (max - min)) * 90;
        return (
          <div key={unit} className="guide-shift-group">
            <p className="mb-3 text-xs text-muted-foreground">
              Shared scale: {min} to {max}
              {unit ? ` ${unit}` : " (unitless)"}
            </p>
            {group.map((p, i) => {
              const real = p.verdict === "Real shift";
              const a = position(p.x),
                b = position(p.y);
              return (
                <div
                  key={`${p.label}-${i}`}
                  data-shift={p.label ?? ""}
                  data-real={String(real)}
                  className="guide-shift-row"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="min-w-0 font-medium">{p.label}</p>
                    <p className="text-sm">
                      <strong>Change: {p.change}</strong>
                      <span className="ml-2 text-muted-foreground">
                        {p.verdict === "Noise" ? (
                          <>
                            Within usual variation<span className="sr-only"> (Noise)</span>
                          </>
                        ) : (
                          p.verdict
                        )}
                      </span>
                    </p>
                  </div>
                  <div className="guide-shift-values">
                    <div>
                      <span>{periods?.before ?? "Reference month"}</span>
                      <strong>
                        {p.x}
                        {unit && ` ${unit}`}
                      </strong>
                      <span>{p.before}</span>
                    </div>
                    <div>
                      <span>{periods?.now ?? "Later month"}</span>
                      <strong>
                        {p.y}
                        {unit && ` ${unit}`}
                      </strong>
                      <span>{p.now}</span>
                    </div>
                  </div>
                  <div className="guide-shift-track" aria-hidden="true">
                    <span
                      className="guide-shift-connection"
                      style={{ left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%` }}
                    />
                    <span
                      className="guide-shift-dot guide-shift-dot--before"
                      style={{ left: `${a}%` }}
                    />
                    <span className="guide-shift-dot" style={{ left: `${b}%` }} />
                  </div>
                  <p className="sr-only">{`${p.x} → ${p.y}${unit && ` ${unit}`}`}</p>
                </div>
              );
            })}
          </div>
        );
      })}
      <p className="mt-3 text-xs text-muted-foreground">
        Higher readings do not automatically mean better quality. Use the supplied status and
        verdict.
      </p>
    </div>
  );
}
