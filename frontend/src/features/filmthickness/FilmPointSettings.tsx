/**
 * T100 Part C (D-100-3): the Film **Points** panel, inside the Standard tab.
 *
 * Which points of a plant x model's walk count towards the dashboard's
 * Horizontal / Vertical boxes, and which of the two each one is. One row per
 * live point, in walk order, with the stop markers and who last changed it.
 *
 * Saving is append-only on the server (every change is a new row, D-99-4) and
 * it rewrites **past months** too, because the dashboard reads the latest
 * setting for every month. So Save asks twice: the warning, then a reason
 * (D-100-6). No reason, no save -- the API's own minimum is three characters
 * and this does not try to be cleverer than it.
 *
 * RO17 (D-RO17-11): every live list can be edited -- add, rename, retire,
 * restore -- whether or not the T99 point rules are on. Counted and H / V
 * are the rules, so their controls and Save appear only with
 * `has_setting`; without it an Admin may switch the rules on, seeing first
 * what would be written. Each point shows the plant's word first and its
 * code beside it (D-RO17-1). Tail labels (D-RO17-12) and the other
 * spellings (D-RO17-13) follow the retired points. Complete stops are shown,
 * not edited.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, filmModelsOptions, filmPointSettingOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FilmPointAdd } from "./FilmPointAdd";
import { PointWalkOrder } from "./PointWalkOrder";
import { PointListTools } from "./PointListTools";
import { EMPTY_POINT_FILTER, matchesPointFilter } from "./point-list-filter";
import { FilmPointRetire } from "./FilmPointRetire";
import { FilmRulesSwitchOn } from "./FilmRulesSwitchOn";
import { FilmTailLabels } from "./FilmTailLabels";
import { PointAliases } from "./PointAliases";
import { PointName, PointRename, PointRestore } from "./PointEdit";
import { POINT_EDIT_COPY, refreshPointWrite } from "./point-edit";
import {
  POINTS_COPY,
  POINT_CHECK_COPY,
  changedPoints,
  type Draft,
  type Orientation,
  type Point,
} from "./film-points";

export function FilmPointSettings({ code, admin }: { code: string; admin: boolean }) {
  const plant = code.toUpperCase();
  const models = useQuery(filmModelsOptions(plant));
  const [model, setModel] = useState("");
  const [filter, setFilter] = useState(EMPTY_POINT_FILTER);
  // D-RO17-10: an offered model with no list can be picked and given its first point.
  const offered = models.data?.offered_without_list ?? [];
  const chosen = model || models.data?.items[0]?.model_code || offered[0] || "";
  const setting = useQuery(filmPointSettingOptions(plant, chosen));
  const [draft, setDraft] = useState<Record<string, Draft>>({});
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();

  const items = setting.data?.items;
  const points = useMemo(() => items ?? [], [items]);
  const changed = useMemo(() => changedPoints(points, draft), [points, draft]);
  const editable = Boolean(setting.data?.has_setting);
  // T109 (D-109-4): the server's own list of what left this walk.
  const retired = setting.data?.retired_items ?? [];

  const save = useMutation({
    mutationFn: () => api().changeFilmPointSetting(plant, chosen, { points: changed, reason }),
    retry: false,
    onSuccess: async () => {
      setDraft({});
      setConfirming(false);
      setReason("");
      await refreshPointWrite(client, plant, "film", chosen);
    },
  });

  const value = (point: Point): Draft =>
    draft[point.point_code] ?? {
      counted: point.counted,
      orientation: (point.orientation ?? "V") as Orientation,
    };
  const edit = (point: Point, next: Partial<Draft>) =>
    setDraft((was) => ({ ...was, [point.point_code]: { ...value(point), ...next } }));
  const visiblePoints = points.filter((point) =>
    matchesPointFilter(filter, {
      point_no: point.point_no,
      code: point.point_code,
      label: point.label,
      counted: value(point).counted,
      orientation: point.orientation === null ? null : value(point).orientation,
    }),
  );

  // T100-FIX: the panel is its own panel now, beside the standards one rather
  // than inside it, so its loading and error states live inside its own
  // heading -- a Viewer's 403 is a thing the Points panel says, not a bare
  // error floating in the Standard tab.
  if (models.isSuccess && models.data.items.length === 0 && offered.length === 0)
    return (
      <section
        className="panel p-5"
        data-testid="film-points-panel"
        aria-label={`${plant} Film points`}
      >
        <h3 className="text-lg font-bold">Film Thickness points</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          No Film Thickness point lists are available at {plant}. Choose Wave Scan to inspect its
          point lists.
        </p>
      </section>
    );

  return (
    <section
      className="film-standards panel mt-6 min-w-0 p-4 sm:p-5"
      aria-label={`${plant} Film points`}
      data-testid="film-points-panel"
    >
      <h3 className="text-lg font-bold">Film Thickness points</h3>
      <p className="mt-1 text-sm text-muted-foreground">{POINTS_COPY.explain}</p>
      {models.isPending && <LoadingState>Loading Film models...</LoadingState>}
      {models.isError && <ApiErrorState error={models.error} retry={() => void models.refetch()} />}
      {models.isSuccess && (
        <>
          <label className="mt-4 block max-w-sm text-sm font-medium" htmlFor="film-points-model">
            Model
            <select
              id="film-points-model"
              data-testid="film-points-model"
              className="mt-1 min-h-11 w-full rounded-md border border-border bg-background px-2 text-sm"
              value={chosen}
              disabled={changed.length > 0 || save.isPending}
              onChange={(event) => {
                setModel(event.target.value);
                setDraft({});
                setConfirming(false);
                setFilter(EMPTY_POINT_FILTER);
              }}
            >
              {models.data.items.map((item) => (
                <option key={item.model_code} value={item.model_code}>
                  {item.display_name ?? item.model_code} ({item.point_count} points)
                </option>
              ))}
              {offered.map((item) => (
                <option key={item} value={item}>
                  {item} ({POINT_EDIT_COPY.noList})
                </option>
              ))}
            </select>
          </label>
          {changed.length > 0 && (
            <p className="mt-2 text-sm text-muted-foreground">
              Save or discard the point changes before choosing another model.
            </p>
          )}

          {setting.isPending ? (
            <LoadingState>Loading points...</LoadingState>
          ) : setting.isError ? (
            <ApiErrorState error={setting.error} retry={() => void setting.refetch()} />
          ) : (
            <>
              {!editable && points.length > 0 && (
                <div className="mt-3 space-y-3">
                  <p role="status" className="text-sm" data-testid="film-points-read-only">
                    {POINTS_COPY.readOnly}
                  </p>
                  {admin && <FilmRulesSwitchOn plant={plant} model={chosen} points={points} />}
                </div>
              )}
              {points.length === 0 && (
                <p className="mt-3 text-sm" data-testid="film-points-empty">
                  {POINT_EDIT_COPY.emptyList}
                </p>
              )}
              <PointListTools
                scope="Film"
                total={points.length}
                shown={visiblePoints.length}
                counted={points.filter((point) => value(point).counted).length}
                filter={filter}
                onChange={setFilter}
              />
              <div className="point-check-table mt-4 rounded-md border border-border">
                <table className="w-full min-w-[640px] text-left text-xs">
                  <caption className="sr-only">
                    {chosen} point catalogue, with stable point numbers, what counts and its Hor /
                    Ver
                  </caption>
                  <thead className="bg-[var(--surface-2)] text-muted-foreground">
                    <tr>
                      {[
                        "Point no.",
                        "Point",
                        "H / V",
                        "Counted",
                        "Stop",
                        "Last change",
                        // T109 / RO17: the write columns, on every live list.
                        POINT_EDIT_COPY.rename,
                        "Retire",
                      ].map((head) => (
                        <th key={head} scope="col" className="px-3 py-2 font-medium">
                          {head}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePoints.map((point) => {
                      const next = value(point);
                      return (
                        <tr
                          key={point.point_code}
                          className="border-t border-border"
                          data-film-point={point.point_code}
                        >
                          <td className="num px-3 py-2">{point.point_no}</td>
                          <th scope="row" className="px-3 py-2 font-mono font-medium">
                            <PointName label={point.label} code={point.point_code} />
                            {/* T109 (D-109-3): a tag, never a grade. It says
                                this point is beyond the plant's standard
                                list for the model; it refuses nothing. */}
                            {point.is_extra && (
                              <span
                                data-testid={`film-point-extra-${point.point_code}`}
                                title={POINT_CHECK_COPY.extraTitle}
                                className="ml-2 rounded-sm border border-border px-1 font-sans text-[0.7rem] font-normal text-muted-foreground"
                              >
                                {POINT_CHECK_COPY.extra}
                              </span>
                            )}
                          </th>
                          {/* D-RO17-11: Counted and H / V are the T99 rules, so
                              their controls exist only where the rules are on. */}
                          {editable ? (
                            <>
                              <td className="px-3 py-2">
                                <select
                                  aria-label={`Horizontal or Vertical ${point.point_code}`}
                                  data-testid={`film-point-orientation-${point.point_code}`}
                                  className="min-h-11 rounded-md border border-border bg-background px-2 text-xs"
                                  value={next.orientation}
                                  disabled={save.isPending}
                                  onChange={(event) =>
                                    edit(point, { orientation: event.target.value as Orientation })
                                  }
                                >
                                  <option value="H">H</option>
                                  <option value="V">V</option>
                                </select>
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  type="checkbox"
                                  aria-label={`Counted ${point.point_code}`}
                                  data-testid={`film-point-counted-${point.point_code}`}
                                  className="size-5"
                                  checked={next.counted}
                                  disabled={save.isPending}
                                  onChange={(event) =>
                                    edit(point, { counted: event.target.checked })
                                  }
                                />
                              </td>
                            </>
                          ) : (
                            <>
                              <td className="px-3 py-2 text-muted-foreground">
                                {point.orientation ?? "-"}
                              </td>
                              <td className="px-3 py-2 text-muted-foreground">-</td>
                            </>
                          )}
                          <td className="px-3 py-2 text-muted-foreground">
                            {point.is_complete_stop ? "Complete stop" : "-"}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">
                            {point.reason ?? "-"}
                            {point.changed_at && (
                              <span className="block">
                                {point.changed_by ? point.changed_by : POINTS_COPY.seed} ·{" "}
                                {point.changed_at.slice(0, 10)}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <PointRename
                              plant={plant}
                              domain="film"
                              model={chosen}
                              code={point.point_code}
                              label={point.label}
                              disabled={save.isPending}
                            />
                          </td>
                          <td className="px-3 py-2">
                            <FilmPointRetire
                              plant={plant}
                              model={chosen}
                              point={point}
                              disabled={save.isPending}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 space-y-3">
                {editable && (
                  <p className="text-sm" data-testid="film-points-changed">
                    {changed.length
                      ? `${changed.length} point${changed.length === 1 ? "" : "s"} changed.`
                      : POINTS_COPY.noChange}
                  </p>
                )}
                {editable &&
                  (!confirming ? (
                    <Button
                      className="min-h-11"
                      data-testid="film-points-save"
                      disabled={changed.length === 0 || save.isPending}
                      onClick={() => setConfirming(true)}
                    >
                      {POINTS_COPY.save}
                    </Button>
                  ) : (
                    <div
                      className="space-y-3 border border-primary bg-[var(--primary-soft)] p-3"
                      data-testid="film-points-confirm"
                      role="alert"
                    >
                      <p className="text-sm font-medium">
                        {POINTS_COPY.warning.replace("{plant}", plant)}
                      </p>
                      <label className="block text-sm font-medium" htmlFor="film-points-reason">
                        {POINTS_COPY.reason}
                        <Input
                          id="film-points-reason"
                          data-testid="film-points-reason"
                          className="mt-1 min-h-11"
                          value={reason}
                          disabled={save.isPending}
                          onChange={(event) => setReason(event.target.value)}
                        />
                      </label>
                      <p className="text-xs text-muted-foreground">{POINTS_COPY.reasonHint}</p>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          className="min-h-11"
                          data-testid="film-points-save-confirm"
                          disabled={reason.trim().length < 3 || save.isPending}
                          onClick={() => save.mutate()}
                        >
                          {POINTS_COPY.save} {changed.length}
                        </Button>
                        <Button
                          variant="outline"
                          className="min-h-11"
                          data-testid="film-points-cancel"
                          disabled={save.isPending}
                          onClick={() => {
                            setConfirming(false);
                            setReason("");
                          }}
                        >
                          {POINTS_COPY.cancel}
                        </Button>
                      </div>
                      {save.isError && <ApiErrorState error={save.error} />}
                    </div>
                  ))}
                {changed.length > 0 && !confirming && (
                  <Button
                    variant="outline"
                    className="min-h-11"
                    disabled={save.isPending}
                    onClick={() => {
                      setDraft({});
                      setReason("");
                      save.reset();
                    }}
                  >
                    Discard point changes
                  </Button>
                )}
                {/* T109 (D-109-5): add is its own write, not part of Save:
                    a new point is one INSERT with its own reason, and it
                    must not wait on an unrelated tick being saved. */}
                <FilmPointAdd
                  key={`${plant}:${chosen}`}
                  plant={plant}
                  model={chosen}
                  hasSetting={editable}
                  hasPoints={points.length > 0}
                />
              </div>

              {points.length > 0 && (
                <details className="point-check-disclosure">
                  <summary>Measuring order</summary>
                  <PointWalkOrder
                    key={`${plant}:${chosen}`}
                    plant={plant}
                    model={chosen}
                    domain="FILMTHICKNESS"
                    admin={admin}
                  />
                </details>
              )}

              {/* T109 (D-109-4): what this list used to walk. The live table
                  above is the walk; these rows are the record of what left
                  it and why, beside readings that are still in History. */}
              <section className="mt-6" aria-label={`${chosen} ${POINT_CHECK_COPY.retiredHeading}`}>
                <h4 className="text-sm font-bold">
                  {POINT_CHECK_COPY.retiredHeading}
                  {retired.length > 0 && (
                    /* T109: the count up front, because a plant whose copied
                       list T83 retired carries dozens of these and the
                       number is the first thing a reader wants. */
                    <span className="ml-2 font-normal text-muted-foreground">{retired.length}</span>
                  )}
                </h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  {POINT_CHECK_COPY.retiredExplain}
                </p>
                {retired.length === 0 ? (
                  <p className="mt-2 text-xs" data-testid="film-points-retired-none">
                    {POINT_CHECK_COPY.retiredNone}
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1 text-xs" data-testid="film-points-retired">
                    {retired.map((point) => (
                      <li
                        key={point.point_code}
                        data-film-retired={point.point_code}
                        className="border-t border-border py-2"
                      >
                        <span className="num mr-2">{point.point_no}</span>
                        <span className="font-mono font-medium">
                          <PointName label={point.label} code={point.point_code} />
                        </span>
                        {point.is_extra && (
                          <span className="ml-2 rounded-sm border border-border px-1 text-[0.7rem] text-muted-foreground">
                            {POINT_CHECK_COPY.extra}
                          </span>
                        )}
                        <span className="block text-muted-foreground">
                          {point.retired_reason} · {point.retired_at.slice(0, 10)}
                        </span>
                        <PointRestore
                          plant={plant}
                          domain="film"
                          model={chosen}
                          code={point.point_code}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <FilmTailLabels
                plant={plant}
                model={chosen}
                labels={setting.data.tail_labels ?? []}
                admin={admin}
              />
              <PointAliases plant={plant} domain="film" model={chosen} admin={admin} />
            </>
          )}
        </>
      )}
    </section>
  );
}
