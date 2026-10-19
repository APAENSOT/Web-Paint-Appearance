/**
 * T114 (D-114-1): Point Check's **Wave Scan** section.
 *
 * Per plant x model, the live list in walk order: zone code, Horizontal /
 * Vertical (fixed by the name, shown only), Counted, the extra tag, the last
 * change, and Retire. The retired points are listed below, greyed, each with
 * when it went and why.
 *
 * Counted is append-only on the server (every change is a new row, D-114-2)
 * and it moves the dashboard for **every** month, so Save asks twice -- the
 * warning, then a reason -- the shape Film's Points panel has (D-100-6).
 * History and Comparison keep every reading whatever this says (D-114-3).
 *
 * Every plant with a Wave Scan list is editable (D-114-1); who sees Point
 * Check at all is `StandardChildrenNav`'s gate, the one Film uses.
 *
 * RO17: each point shows the plant's word first and its code beside it
 * (D-RO17-1), with Rename (D-RO17-6); a retired point can be restored
 * (D-RO17-9); an offered model with no list can be picked and given its
 * first point (D-RO17-10); the other spellings follow (D-RO17-13).
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, wsPointListOptions, wsPointModelsOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { WsPointAdd } from "./WsPointAdd";
import { PointWalkOrder } from "./PointWalkOrder";
import { PointListTools } from "./PointListTools";
import { EMPTY_POINT_FILTER, matchesPointFilter } from "./point-list-filter";
import { WsPointRetire } from "./WsPointRetire";
import { PointAliases } from "./PointAliases";
import { PointName, PointRename, PointRestore } from "./PointEdit";
import { POINT_EDIT_COPY, refreshPointWrite } from "./point-edit";
import { WS_POINTS_COPY, changedWsPoints, type WsPoint } from "./ws-points";

export function WsPointSettings({ code, admin }: { code: string; admin: boolean }) {
  const plant = code.toUpperCase();
  const models = useQuery(wsPointModelsOptions(plant));
  const [model, setModel] = useState("");
  const [filter, setFilter] = useState(EMPTY_POINT_FILTER);
  const offered = models.data?.offered_without_list ?? [];
  const chosen = model || models.data?.items[0]?.model_code || offered[0] || "";
  const list = useQuery(wsPointListOptions(plant, chosen));
  const [draft, setDraft] = useState<Record<string, boolean>>({});
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();

  const items = list.data?.items;
  const points = useMemo(() => items ?? [], [items]);
  const changed = useMemo(() => changedWsPoints(points, draft), [points, draft]);
  const retired = list.data?.retired_items ?? [];

  const save = useMutation({
    mutationFn: () => api().changeWsPointSetting(plant, chosen, { points: changed, reason }),
    retry: false,
    onSuccess: async () => {
      setDraft({});
      setConfirming(false);
      setReason("");
      await refreshPointWrite(client, plant, "wavescan", chosen);
    },
  });

  const counted = (point: WsPoint) => draft[point.zone_code] ?? point.counted;
  const visiblePoints = points.filter((point) =>
    matchesPointFilter(filter, {
      point_no: point.point_no,
      code: point.zone_code,
      label: point.label,
      counted: counted(point),
      orientation: point.tolerance_group === "Horizontal" ? "H" : "V",
    }),
  );

  return (
    <section
      className="panel min-w-0 p-4 sm:p-5"
      aria-label={`${plant} ${WS_POINTS_COPY.heading} points`}
      data-testid="ws-points-panel"
    >
      <h3 className="text-lg font-bold">{WS_POINTS_COPY.heading}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{WS_POINTS_COPY.explain}</p>
      {models.isPending && <LoadingState>Loading Wave Scan models...</LoadingState>}
      {models.isError && <ApiErrorState error={models.error} retry={() => void models.refetch()} />}
      {models.isSuccess && models.data.items.length === 0 && offered.length === 0 && (
        <p className="mt-3 text-sm" data-testid="ws-points-none">
          {WS_POINTS_COPY.none}
        </p>
      )}
      {models.isSuccess && (models.data.items.length > 0 || offered.length > 0) && (
        <>
          <label className="mt-4 block max-w-sm text-sm font-medium" htmlFor="ws-points-model">
            Model
            <select
              id="ws-points-model"
              data-testid="ws-points-model"
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
                  {item.display_name ?? item.model_code} ({item.point_count} points,{" "}
                  {item.counted_count} counted)
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

          {list.isPending ? (
            <LoadingState>Loading points...</LoadingState>
          ) : list.isError ? (
            <ApiErrorState error={list.error} retry={() => void list.refetch()} />
          ) : (
            <>
              {points.length === 0 && (
                <p className="mt-3 text-sm" data-testid="ws-points-empty">
                  {POINT_EDIT_COPY.emptyList}
                </p>
              )}
              <PointListTools
                scope="Wave Scan"
                total={points.length}
                shown={visiblePoints.length}
                counted={points.filter(counted).length}
                filter={filter}
                onChange={setFilter}
              />
              <div className="point-check-table mt-4 rounded-md border border-border">
                <table className="w-full min-w-[640px] text-left text-xs">
                  <caption className="sr-only">
                    {chosen} Wave Scan point catalogue with stable point numbers and what the
                    dashboard counts
                  </caption>
                  <thead className="bg-[var(--surface-2)] text-muted-foreground">
                    <tr>
                      {[
                        "Point no.",
                        "Zone code",
                        "H / V",
                        WS_POINTS_COPY.counted,
                        "Last change",
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
                    {visiblePoints.map((point) => (
                      <tr
                        key={point.zone_code}
                        className="border-t border-border"
                        data-ws-point={point.zone_code}
                      >
                        <td className="num px-3 py-2">{point.point_no}</td>
                        <th scope="row" className="px-3 py-2 font-mono font-medium">
                          <PointName label={point.label} code={point.zone_code} />
                          {point.is_extra && (
                            <span
                              data-testid={`ws-point-extra-${point.zone_code}`}
                              title={WS_POINTS_COPY.extraTitle}
                              className="ml-2 rounded-sm border border-border px-1 font-sans text-[0.7rem] font-normal text-muted-foreground"
                            >
                              {WS_POINTS_COPY.extra}
                            </span>
                          )}
                        </th>
                        <td className="px-3 py-2" data-testid={`ws-point-hv-${point.zone_code}`}>
                          {point.tolerance_group === "Horizontal" ? "H" : "V"}
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            aria-label={`Counted ${point.zone_code}`}
                            data-testid={`ws-point-counted-${point.zone_code}`}
                            className="size-5"
                            checked={counted(point)}
                            disabled={save.isPending}
                            onChange={(event) =>
                              setDraft((was) => ({
                                ...was,
                                [point.zone_code]: event.target.checked,
                              }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {point.reason ?? point.note ?? "-"}
                          {point.changed_at && (
                            <span className="block">
                              {point.changed_by ?? "-"} · {point.changed_at.slice(0, 10)}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <PointRename
                            plant={plant}
                            domain="wavescan"
                            model={chosen}
                            code={point.zone_code}
                            label={point.label}
                            disabled={save.isPending}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <WsPointRetire
                            plant={plant}
                            model={chosen}
                            point={point}
                            disabled={save.isPending}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 space-y-3">
                <p className="text-sm" data-testid="ws-points-changed">
                  {changed.length
                    ? `${changed.length} point${changed.length === 1 ? "" : "s"} changed.`
                    : WS_POINTS_COPY.noChange}
                </p>
                {!confirming ? (
                  <Button
                    className="min-h-11"
                    data-testid="ws-points-save"
                    disabled={changed.length === 0 || save.isPending}
                    onClick={() => setConfirming(true)}
                  >
                    {WS_POINTS_COPY.save}
                  </Button>
                ) : (
                  <div
                    className="space-y-3 border border-primary bg-[var(--primary-soft)] p-3"
                    data-testid="ws-points-confirm"
                    role="alert"
                  >
                    <p className="text-sm font-medium">
                      {WS_POINTS_COPY.warning.replace("{plant}", plant)}
                    </p>
                    <label className="block text-sm font-medium" htmlFor="ws-points-reason">
                      {WS_POINTS_COPY.reason}
                      <Input
                        id="ws-points-reason"
                        data-testid="ws-points-reason"
                        className="mt-1 min-h-11"
                        value={reason}
                        disabled={save.isPending}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </label>
                    <p className="text-xs text-muted-foreground">{WS_POINTS_COPY.reasonHint}</p>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        className="min-h-11"
                        data-testid="ws-points-save-confirm"
                        disabled={reason.trim().length < 3 || save.isPending}
                        onClick={() => save.mutate()}
                      >
                        {WS_POINTS_COPY.save} {changed.length}
                      </Button>
                      <Button
                        variant="outline"
                        className="min-h-11"
                        data-testid="ws-points-cancel"
                        disabled={save.isPending}
                        onClick={() => {
                          setConfirming(false);
                          setReason("");
                        }}
                      >
                        {WS_POINTS_COPY.cancel}
                      </Button>
                    </div>
                    {save.isError && <ApiErrorState error={save.error} />}
                  </div>
                )}
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
                {/* D-114-6: its own write with its own reason, like Film's add. */}
                <WsPointAdd
                  plant={plant}
                  model={chosen}
                  choices={list.data.zone_choices}
                  horizontalWords={list.data.horizontal_words}
                  admin={admin}
                />
              </div>

              {points.length > 0 && (
                <details className="point-check-disclosure">
                  <summary>Measuring order</summary>
                  <PointWalkOrder
                    key={`${plant}:${chosen}`}
                    plant={plant}
                    model={chosen}
                    domain="WAVESCAN"
                    admin={admin}
                  />
                </details>
              )}

              <section
                className="mt-6"
                aria-label={`${chosen} Wave Scan ${WS_POINTS_COPY.retiredHeading}`}
              >
                <h4 className="text-sm font-bold">
                  {WS_POINTS_COPY.retiredHeading}
                  {retired.length > 0 && (
                    <span className="ml-2 font-normal text-muted-foreground">{retired.length}</span>
                  )}
                </h4>
                <p className="mt-1 text-xs text-muted-foreground">
                  {WS_POINTS_COPY.retiredExplain}
                </p>
                {retired.length === 0 ? (
                  <p className="mt-2 text-xs" data-testid="ws-points-retired-none">
                    {WS_POINTS_COPY.retiredNone}
                  </p>
                ) : (
                  <ul
                    className="mt-2 space-y-1 text-xs text-muted-foreground"
                    data-testid="ws-points-retired"
                  >
                    {retired.map((point) => (
                      <li
                        key={point.zone_code}
                        data-ws-retired={point.zone_code}
                        className="border-t border-border py-2"
                      >
                        <span className="num mr-2">{point.point_no}</span>
                        <span className="font-mono font-medium">
                          <PointName label={point.label} code={point.zone_code} />
                        </span>
                        <span className="ml-2">
                          {point.tolerance_group === "Horizontal" ? "H" : "V"}
                        </span>
                        {point.is_extra && (
                          <span className="ml-2 rounded-sm border border-border px-1 text-[0.7rem]">
                            {WS_POINTS_COPY.extra}
                          </span>
                        )}
                        <span className="block">
                          {point.retired_reason} · {point.retired_at.slice(0, 10)}
                        </span>
                        <PointRestore
                          plant={plant}
                          domain="wavescan"
                          model={chosen}
                          code={point.zone_code}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <PointAliases plant={plant} domain="wavescan" model={chosen} admin={admin} />
            </>
          )}
        </>
      )}
    </section>
  );
}
