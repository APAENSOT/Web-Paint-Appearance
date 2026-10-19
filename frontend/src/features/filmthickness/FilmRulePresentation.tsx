import { displayValue, limitFields, type Layer, type Resolved } from "./film-standards";
export function RuleValues({
  resolved,
  layer,
  orientation,
}: {
  resolved: Resolved;
  layer: Layer;
  orientation: string;
}) {
  const { rule, inherited } = resolved;
  return (
    <div className="min-w-0 text-sm">
      <p className="mb-2 font-semibold">
        {orientation}{" "}
        {inherited && (
          <span className="ml-2 text-xs font-normal text-muted-foreground">Inherited</span>
        )}
      </p>
      {rule ? (
        <dl className="space-y-1">
          {limitFields(layer).map(([key, label]) => (
            <div key={key} className="flex flex-wrap justify-between gap-x-3">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="num">{displayValue(rule[key])}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-muted-foreground">No standard</p>
      )}
    </div>
  );
}
export function RuleSources({ h, v }: { h: Resolved; v: Resolved }) {
  if (!h.rule && !v.rule) return null;
  return (
    <details className="mt-3 text-sm">
      <summary className="min-h-11 cursor-pointer py-3">Source details</summary>
      <div className="grid gap-3 md:grid-cols-2">
        {(
          [
            ["Horizontal", h],
            ["Vertical", v],
          ] as const
        ).map(
          ([label, resolved]) =>
            resolved.rule && (
              <div
                key={label}
                className="min-w-0 space-y-1 break-words rounded border border-border p-3"
              >
                <p className="font-semibold">
                  {label}
                  {resolved.inherited ? " — Plant-wide source (Inherited)" : ""}
                </p>
                <p>Document reference: {resolved.rule.source_document ?? "Not provided"}</p>
                <p className="whitespace-pre-wrap">Source note: {resolved.rule.source_note}</p>
                <p>
                  Published:{" "}
                  <time dateTime={resolved.rule.created_at}>
                    {new Intl.DateTimeFormat("en-GB", {
                      timeZone: "Asia/Bangkok",
                      dateStyle: "medium",
                      timeStyle: "medium",
                    }).format(new Date(resolved.rule.created_at))}
                  </time>{" "}
                  (Asia/Bangkok)
                </p>
              </div>
            ),
        )}
      </div>
    </details>
  );
}
