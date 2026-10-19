import { useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, RefreshCw, FileText } from "lucide-react";
import { filmStandardsOptions, meOptions } from "@/api/queries";
import { isAdmin } from "@/api/roles";
import { AccessDenied } from "@/features/shell/AccessDenied";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetTrigger } from "@/components/ui/sheet";
import { FilmPublishDialog } from "./FilmPublishDialog";
import { FilmSources } from "./FilmSources";
import { RuleValues } from "./FilmRulePresentation";
import {
  colourGroups,
  displayValue,
  layerName,
  limitFields,
  plantTemplate,
  resolveRow,
  retainedRules,
  type FilmStandardsOut,
  type Layer,
  type Resolved,
} from "./film-standards";
import "./film-standards.css";
import "./film-standards-polish.css";
export { RuleSources, RuleValues } from "./FilmRulePresentation";

type Editing = { layer: Layer; color: string | null; h: Resolved; v: Resolved };
type Edit = (row: Editing, button: HTMLButtonElement) => void;
/**
 * T100-FIX (D-100-8): the Standard tab's Film section is two things with two
 * audiences, so it is two components.
 *
 * Publishing a standard stays Admin-only -- the owner's "ignore roles"
 * decision was about Film **points**, not about standards.
 *
 * T109 (D-109-1): the Points panel is **no longer here**. It is the Film
 * section of Point Check, Standard's own entry, because the points a plant
 * walks are not a standard a reading is measured against. Standards stayed
 * exactly where they were.
 */
export function FilmStandards({ code }: { code: string }) {
  return <FilmStandardsAdmin code={code} />;
}

function FilmStandardsAdmin({ code }: { code: string }) {
  const identity = useQuery(meOptions);
  const allowed = identity.isSuccess && isAdmin(identity.data.principal);
  const query = useQuery({ ...filmStandardsOptions(code), enabled: allowed });
  const [published, setPublished] = useState(false);
  if (identity.isPending) return <LoadingState>Loading API identity...</LoadingState>;
  if (identity.isError)
    return <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />;
  if (!allowed) return <AccessDenied requiredRole="Admin" />;
  return (
    <section
      className="film-standards panel min-w-0 p-4 sm:p-5"
      aria-label={`${code} Film standards`}
    >
      {query.isError || query.isPending ? (
        <>
          <h2 className="text-xl font-bold">Film Thickness</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {code.toUpperCase()} · Latest published standards in microns (µm).
          </p>
          {published && (
            <p role="status" className="mt-3 text-sm">
              New standard version published
            </p>
          )}
          {query.isError ? (
            <ApiErrorState error={query.error} retry={() => void query.refetch()} />
          ) : (
            <LoadingState>Loading Film standards...</LoadingState>
          )}
        </>
      ) : (
        <FilmStandardsBody
          data={query.data}
          published={published}
          onPublished={() => setPublished(true)}
          refreshing={query.isFetching}
          onRefresh={() => void query.refetch()}
        />
      )}
    </section>
  );
}
function SharedMetrics({ h, v, layer }: { h: Resolved; v: Resolved; layer: Layer }) {
  const fields = limitFields(layer);
  return (
    <table className="mb-5 w-full table-fixed text-sm">
      <thead>
        <tr>
          <th className="w-[40%]" aria-label="Limit" />
          <th scope="col" className="pb-3 text-right font-medium text-muted-foreground">
            Horizontal
          </th>
          <th scope="col" className="pb-3 text-right font-medium text-muted-foreground">
            Vertical
          </th>
        </tr>
      </thead>
      <tbody>
        {fields.map(([field, label]) => (
          <tr key={field}>
            <th scope="row" className="py-2 text-left font-normal text-muted-foreground">
              {label}
            </th>
            {[h, v].map((resolved, i) => (
              <td key={i} className="py-2 text-right">
                <span
                  className={
                    resolved.rule ? "num text-base font-semibold" : "text-xs text-muted-foreground"
                  }
                >
                  {resolved.rule ? displayValue(resolved.rule[field]) : "No standard"}
                </span>
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
function Retained({ data, layer }: { data: FilmStandardsOut; layer: Layer }) {
  const rows = retainedRules(data, layer);
  if (!rows.length) return null;
  return (
    <details className="film-disclosure rounded border border-border px-4">
      <summary className="min-h-11 cursor-pointer py-3 font-semibold">
        Not offered · {layerName(layer)}
      </summary>
      <div className="divide-y divide-border">
        {rows.map((r) => {
          const { h, v } = resolveRow(data, layer, r.color_name, true);
          return (
            <article key={r.color_name} aria-label={`${layer} ${r.color_name}`} className="py-4">
              <h4 className="mb-3 font-semibold">{r.color_name}</h4>
              <div className="grid gap-4 sm:grid-cols-2">
                <RuleValues layer={layer} orientation="Horizontal" resolved={h} />
                <RuleValues layer={layer} orientation="Vertical" resolved={v} />
              </div>
            </article>
          );
        })}
      </div>
    </details>
  );
}
function ExceptionRow({
  data,
  layer,
  color,
  onEdit,
}: {
  data: FilmStandardsOut;
  layer: Layer;
  color: string | null;
  onEdit: Edit;
}) {
  const { h, v } = resolveRow(data, layer, color);
  return (
    <article
      aria-label={`${layer} ${color ?? "Plant-wide"}`}
      className="border-t border-border py-4"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h4 className="font-semibold">
          {layerName(layer)} · {color ?? "Plant-wide"}
        </h4>
        <Button
          variant="outline"
          className="min-h-11"
          onClick={(e) => onEdit({ layer, color, h, v }, e.currentTarget)}
        >
          Adjust standard
        </Button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <RuleValues resolved={h} layer={layer} orientation="Horizontal" />
        <RuleValues resolved={v} layer={layer} orientation="Vertical" />
      </div>
    </article>
  );
}
function OrientationCells({ resolved, label }: { resolved: Resolved; label: string }) {
  return (
    <>
      {limitFields("BASE").map(([field, name]) => (
        <td key={field} className="film-number-cell px-3 py-3 text-right">
          <span className="film-mobile-label text-muted-foreground">
            {label} {name}
          </span>
          <div>
            <span className={resolved.rule ? "num font-medium" : "text-muted-foreground"}>
              {resolved.rule ? displayValue(resolved.rule[field]) : "No standard"}
            </span>
            {resolved.inherited && (
              <span className="ml-2 text-xs text-muted-foreground">Inherited</span>
            )}
          </div>
        </td>
      ))}
    </>
  );
}
function ColourTable({
  data,
  layer,
  search,
  onEdit,
}: {
  data: FilmStandardsOut;
  layer: Layer;
  search: string;
  onEdit: Edit;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const groups = colourGroups(data.colors, search);
  const searching = Boolean(search.trim());
  const wide = data.rules.find(
    (r) => r.layer_code === layer && r.color_name === null && (r.h || r.v),
  );
  return (
    <section aria-label={`${layer} colour standards`} className="film-layer min-w-0 space-y-3">
      <h4 className="text-lg font-semibold">{layerName(layer)}</h4>
      {data.colors.length === 0 ? (
        <p className="rounded border border-border p-4 text-sm text-muted-foreground">
          No offered colours for this plant
        </p>
      ) : groups.length === 0 ? (
        <p className="rounded border border-border p-4 text-sm text-muted-foreground">
          No matching colours
        </p>
      ) : (
        groups.map((group) => {
          const open = searching || expanded[group.key] !== false;
          return (
            <section
              key={group.key}
              aria-label={`${layer} family ${group.name}`}
              className="film-family-table overflow-hidden rounded border border-border"
            >
              <button
                type="button"
                className="flex min-h-11 w-full items-center justify-between gap-3 bg-[var(--surface-2)] px-4 py-3 text-left text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ring"
                aria-expanded={open}
                onClick={() => {
                  if (!searching) setExpanded((prev) => ({ ...prev, [group.key]: !open }));
                }}
              >
                <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  <span>{group.name}</span>
                  <span className="film-family-table__count" aria-hidden="true">
                    {group.colors.length} {group.colors.length === 1 ? "colour" : "colours"}
                  </span>
                </span>
                <ChevronDown
                  aria-hidden
                  className={`size-4 shrink-0 ${open ? "" : "-rotate-90"}`}
                />
              </button>
              {open && (
                <table className="film-colour-table w-full table-fixed text-sm">
                  <thead className="text-muted-foreground">
                    <tr>
                      <th
                        scope="col"
                        rowSpan={2}
                        className="w-[24%] px-4 py-3 text-left font-medium"
                      >
                        Colour
                      </th>
                      <th scope="colgroup" colSpan={2} className="px-2 pt-3 text-right font-medium">
                        Horizontal (µm)
                      </th>
                      <th scope="colgroup" colSpan={2} className="px-2 pt-3 text-right font-medium">
                        Vertical (µm)
                      </th>
                      <th
                        scope="col"
                        rowSpan={2}
                        className="w-[19%] px-3 py-3 text-right font-medium"
                      >
                        Action
                      </th>
                    </tr>
                    <tr>
                      {["Horizontal", "Vertical"].flatMap((orientation) =>
                        limitFields("BASE").map(([, label]) => (
                          <th
                            scope="col"
                            key={`${orientation}-${label}`}
                            className="px-3 pb-3 pt-1 text-right text-xs font-normal"
                          >
                            {label}
                          </th>
                        )),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {group.colors.map((color) => {
                      const { own, h, v } = resolveRow(data, layer, color.color_name);
                      return (
                        <tr
                          key={color.color_name}
                          aria-label={`${layer} ${color.color_name}`}
                          className="border-t border-border"
                        >
                          <th
                            scope="row"
                            className="film-colour-name px-4 py-3 text-left font-semibold"
                          >
                            {color.color_name}
                          </th>
                          <OrientationCells resolved={h} label="Horizontal" />
                          <OrientationCells resolved={v} label="Vertical" />
                          <td className="film-action px-3 py-3 text-right">
                            <Button
                              variant="outline"
                              className="min-h-11 max-w-full whitespace-normal"
                              onClick={(e) =>
                                onEdit({ layer, color: color.color_name, h, v }, e.currentTarget)
                              }
                            >
                              {own?.h || own?.v ? "Adjust standard" : "Set standard"}
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          );
        })
      )}
      {wide && (
        <details className="film-disclosure rounded border border-border px-4">
          <summary className="min-h-11 cursor-pointer py-3 font-semibold">
            Existing exceptions
          </summary>
          <p className="pb-3 text-sm text-muted-foreground">
            This existing Plant-wide rule supplies inherited values where a colour has no own rule.
          </p>
          <ExceptionRow data={data} layer={layer} color={null} onEdit={onEdit} />
        </details>
      )}
      <Retained data={data} layer={layer} />
    </section>
  );
}
function FilmStandardsBody({
  data,
  published,
  onPublished,
  refreshing,
  onRefresh,
}: {
  data: FilmStandardsOut;
  published: boolean;
  onPublished: () => void;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [sources, setSources] = useState(false);
  const [search, setSearch] = useState("");
  const opener = useRef<HTMLButtonElement | null>(null);
  const onEdit: Edit = (row, button) => {
    opener.current = button;
    setEditing(row);
  };
  const template = plantTemplate(data.plant_code);
  const exceptions = template
    ? data.rules
        .filter(
          (r) =>
            template.shared.includes(r.layer_code) &&
            r.color_name !== null &&
            data.colors.some((c) => c.color_name === r.color_name) &&
            (r.h || r.v),
        )
        .sort(
          (a, b) =>
            template.shared.indexOf(a.layer_code) - template.shared.indexOf(b.layer_code) ||
            a.color_name!.localeCompare(b.color_name!),
        )
    : [];
  return (
    <>
      <header className="film-standards__header flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold">Film Thickness</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {data.plant_code} · Latest published standards in microns (µm).
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            className="min-h-11"
            disabled={refreshing || editing !== null}
            onClick={onRefresh}
          >
            <RefreshCw aria-hidden className="size-4" />
            Refresh
          </Button>
          <Sheet open={sources} onOpenChange={setSources}>
            <SheetTrigger asChild>
              <Button variant="outline" className="min-h-11" disabled={editing !== null}>
                <FileText aria-hidden className="size-4" />
                Sources
              </Button>
            </SheetTrigger>
            {sources && <FilmSources data={data} />}
          </Sheet>
        </div>
      </header>
      {published && (
        <p role="status" className="mt-3 text-sm">
          New standard version published
        </p>
      )}
      {template ? (
        <div className="mt-6 space-y-7">
          <section aria-label="Shared standards" className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold">Shared standards</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Apply to all offered colours.
                {exceptions.length > 0 &&
                  " Existing colour exceptions take precedence for their orientation."}
              </p>
            </div>
            <div className="film-shared-grid">
              {template.shared.map((layer) => {
                const { own, h, v } = resolveRow(data, layer, null);
                return (
                  <article
                    key={layer}
                    aria-label={`${layer} Plant-wide`}
                    className="film-shared-card flex min-w-0 flex-col rounded border border-border bg-[var(--surface-2)] p-4"
                  >
                    <h4 className="mb-4 text-lg font-semibold">{layerName(layer)}</h4>
                    <SharedMetrics h={h} v={v} layer={layer} />
                    <Button
                      variant="outline"
                      className="mt-auto min-h-11 self-start"
                      onClick={(e) => onEdit({ layer, color: null, h, v }, e.currentTarget)}
                    >
                      {own?.h || own?.v ? "Adjust standard" : "Set standard"}
                    </Button>
                  </article>
                );
              })}
            </div>
            {exceptions.length > 0 && (
              <details className="film-disclosure rounded border border-border px-4">
                <summary className="min-h-11 cursor-pointer py-3 font-semibold">
                  Existing exceptions
                </summary>
                {exceptions.map((r) => (
                  <ExceptionRow
                    key={`${r.layer_code}-${r.color_name}`}
                    data={data}
                    layer={r.layer_code}
                    color={r.color_name}
                    onEdit={onEdit}
                  />
                ))}
              </details>
            )}
            {template.shared.map((layer) => (
              <Retained key={layer} data={data} layer={layer} />
            ))}
          </section>
          <div className="film-colour-toolbar flex flex-wrap items-end justify-between gap-3 border-t border-border pt-5">
            <div className="basis-full">
              <h3 className="text-lg font-semibold">Colour standards</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {data.colors.length} offered {data.colors.length === 1 ? "colour" : "colours"} ·
                limits by coating and orientation
              </p>
            </div>
            <label className="w-full max-w-sm text-sm font-medium" htmlFor="film-colour-search">
              Find a colour
              <Input
                id="film-colour-search"
                className="mt-2 min-h-11"
                placeholder="Search offered colours"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <Link
              to="/plant/$code"
              params={{ code: data.plant_code }}
              search={{ standardView: "family" }}
              className="inline-flex min-h-11 items-center rounded border border-border px-4 text-sm font-medium hover:bg-[var(--surface-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              Manage colours
            </Link>
          </div>
          {template.colours.map((layer) => (
            <ColourTable key={layer} data={data} layer={layer} search={search} onEdit={onEdit} />
          ))}
        </div>
      ) : (
        <p className="mt-6 text-sm">Film standards layout is unavailable for this plant.</p>
      )}
      {editing && (
        <FilmPublishDialog
          plant={data.plant_code}
          {...editing}
          onClose={() => setEditing(null)}
          onFocusReturn={() => opener.current?.focus()}
          onPublished={() => {
            setEditing(null);
            onPublished();
            void client.invalidateQueries({
              queryKey: filmStandardsOptions(data.plant_code).queryKey,
              exact: true,
            });
          }}
        />
      )}
    </>
  );
}
