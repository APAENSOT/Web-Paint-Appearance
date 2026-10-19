import { useState, type Dispatch } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { comparisonMonthlyPreviewOptions, comparisonVehiclesOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import {
  laneMonths,
  monthLabel,
  type Board,
  type BoardAction,
  type BoardItem,
} from "./comparison-board";
import { BoxStage } from "./StudioCharts";
import { monthlyEntries } from "./studio-series";
import { ItemControls } from "./StudioBoardItem";
import { MonthlyProfile } from "./MonthlyStudioProfile";
import "./comparison-studio.css";
export function ComparisonStudio({
  code,
  board,
  dispatch,
}: {
  code: string;
  board: Board;
  dispatch: Dispatch<BoardAction>;
}) {
  const [scope, setScope] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [destination, setDestination] = useState("");
  const [groupName, setGroupName] = useState("Group A");
  const [focus, setFocus] = useState("");
  const discovery = useQuery(
    comparisonVehiclesOptions(code, { domain: board.domain, limit: 1, offset: 0 }),
  );
  const options = useQuery(
    comparisonVehiclesOptions(code, {
      domain: board.domain,
      month: scope.length ? scope : discovery.data?.available_months,
      limit: 1,
      offset: 0,
    }),
  );
  const lane = board.lanes.find((l) => l.id === board.active && l.domain === board.domain);
  const destinationGroup = lane?.items.find(
    (item) => item.id === destination && item.kind === "group",
  );
  const effective = lane ? laneMonths(lane) : [];
  const shelf = useQuery({
    ...comparisonVehiclesOptions(code, {
      domain: board.domain,
      month: effective.length ? effective : discovery.data?.available_months,
      model: lane?.model,
      limit: 1,
      offset: 0,
    }),
    enabled: !!lane,
  });
  const items = lane?.items.filter((i) => i.months.length) ?? [];
  const reads = useQueries({
    queries: items.map((item) =>
      comparisonMonthlyPreviewOptions(code, {
        domain: board.domain,
        model: lane!.model,
        metric: board.metric,
        months: item.months,
      }),
    ),
  });
  const lanePreview = useQuery({
    ...comparisonMonthlyPreviewOptions(code, {
      domain: board.domain,
      model: lane?.model ?? "",
      metric: board.metric,
      months: effective,
    }),
    enabled: !!lane && effective.length > 0,
  });
  // Preview supplies domain colour order. Availability adds colours without this metric.
  const colors = [
    ...new Set([
      ...(lanePreview.data?.group_means.map((g) => g.color) ?? []),
      ...(shelf.data?.color_options ?? []),
    ]),
  ];
  const focusedIndex = Math.max(
    0,
    items.findIndex((item) => item.id === focus),
  );
  const focusedItem = items[focusedIndex];
  const focusedRead = reads[focusedIndex];
  const returnedEntries = reads.flatMap((q, i) =>
    q.data ? monthlyEntries(q.data, items[i], (c) => !board.hidden.includes(c), colors) : [],
  );
  const entries = colors.length
    ? colors.flatMap((color) => returnedEntries.filter((entry) => entry.color === color))
    : returnedEntries;
  const addMonth = (month: string) => {
    if (!lane) return;
    if (destinationGroup) {
      const group = destinationGroup;
      if (group && !group.months.includes(month)) {
        dispatch({ type: "add-member", lane: lane.id, id: group.id, month });
      }
    } else if (!lane.items.some((i) => i.kind === "month" && i.months[0] === month))
      dispatch({
        type: "add",
        lane: lane.id,
        item: { id: crypto.randomUUID(), kind: "month", name: month, months: [month] },
      });
  };
  return (
    <div className="studio" aria-label="Comparison Studio">
      <header>
        <p className="eyebrow">Monthly comparison</p>
        <h1>Measured months</h1>
        <p className="cv-muted">
          Compose months by model. Compare distributions, then focus on a location profile.
        </p>
      </header>
      <section className="studio-panel studio-toolbar" aria-label="Monthly controls">
        <label>
          Domain
          <select
            className="cv-input"
            aria-label="Monthly domain"
            value={board.domain}
            onChange={(e) => {
              dispatch({ type: "domain", domain: e.target.value as Board["domain"] });
              setScope([]);
              setModel("");
              setDestination("");
            }}
          >
            <option value="WAVESCAN">WaveScan</option>
            <option value="FILMTHICKNESS">Film Thickness</option>
          </select>
        </label>
        <label>
          Metric
          <select
            className="cv-input"
            aria-label="Monthly metric"
            value={board.metric}
            onChange={(e) =>
              dispatch({ type: "metric", metric: e.target.value as Board["metric"] })
            }
          >
            {(board.domain === "WAVESCAN" ? ["cf"] : ["ecoat", "primer", "base", "clear"]).map(
              (m) => (
                <option key={m} value={m}>
                  {m.toUpperCase()}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          Model
          <select
            className="cv-input"
            aria-label="Add model lane"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            <option value="">Choose model</option>
            {options.data?.model_options.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <button
          className="cv-button"
          disabled={!model || !options.data?.model_options.includes(model)}
          onClick={() => {
            dispatch({
              type: "lane",
              lane: { id: `${board.domain}:${model}`, domain: board.domain, model, items: [] },
            });
            setDestination("");
          }}
        >
          Add model
        </button>
        <details>
          <summary>Model availability months</summary>
          <p className="cv-muted">
            All measured months by default. Choose a scope to discover models over those months.
          </p>
          {discovery.data?.available_months.map((m) => (
            <label className="cv-choice" key={m}>
              <input
                type="checkbox"
                checked={scope.includes(m)}
                onChange={() =>
                  setScope(scope.includes(m) ? scope.filter((s) => s !== m) : [...scope, m])
                }
              />
              {m}
            </label>
          ))}
        </details>
      </section>
      {[discovery, options].map((q, i) =>
        q.isError ? <ApiErrorState key={i} error={q.error} retry={() => void q.refetch()} /> : null,
      )}
      {(discovery.isPending || options.isPending) && (
        <LoadingState>Loading measured months and model availability...</LoadingState>
      )}
      <section className="studio-panel" aria-label="Measured month shelf">
        <div className="studio-toolbar">
          <h2>Measured months</h2>
          {lane && (
            <label>
              Add destination
              <select
                className="cv-input"
                value={destinationGroup?.id ?? ""}
                aria-label="Shelf destination"
                onChange={(e) => setDestination(e.target.value)}
              >
                <option value="">Individual card / {lane.model}</option>
                {lane.items
                  .filter((i) => i.kind === "group")
                  .map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name}
                    </option>
                  ))}
              </select>
            </label>
          )}
        </div>
        {!discovery.data?.available_months.length && discovery.isSuccess && (
          <p className="cv-empty">There are no active measured months in this domain.</p>
        )}
        {!lane && <p className="cv-empty">Choose a model and add its lane to begin.</p>}
        {shelf.isError && <ApiErrorState error={shelf.error} retry={() => void shelf.refetch()} />}
        <div className="studio-shelf">
          {discovery.data?.available_months.map((month) => (
            <button
              className="studio-month"
              disabled={
                !lane ||
                (destinationGroup
                  ? destinationGroup.months.includes(month)
                  : lane.items.some((item) => item.kind === "month" && item.months[0] === month))
              }
              key={month}
              data-used={lane?.items.some((i) => i.months.includes(month))}
              onClick={() => addMonth(month)}
              aria-label={`Add ${monthLabel(month)} to ${lane?.model ?? "lane"}`}
            >
              <span>MEASURED</span>
              <strong>{monthLabel(month)}</strong>
              <span>+ Add to {destinationGroup ? "group" : "board"}</span>
            </button>
          ))}
        </div>
      </section>
      <section aria-label="Comparison board">
        <div className="studio-toolbar">
          <h2>Board</h2>
          <p className="cv-muted">
            Groups average monthly means equally. This board is never saved.
          </p>
        </div>
        {board.lanes
          .filter((l) => l.domain === board.domain)
          .map((l) => (
            <section
              className="studio-lane"
              data-active={l.id === board.active}
              aria-label={`${l.model} model lane`}
              key={l.id}
            >
              <div className="studio-toolbar">
                <h3>{l.model}</h3>
                <button
                  className="cv-button"
                  aria-pressed={l.id === board.active}
                  onClick={() => {
                    dispatch({ type: "active", id: l.id });
                    setDestination("");
                  }}
                >
                  View {l.model} charts
                </button>
                <details className="studio-lane-actions">
                  <summary aria-label={`Lane actions for ${l.model}`}>Lane actions</summary>
                  <div className="studio-action-menu">
                    {" "}
                    <button
                      className="cv-button"
                      disabled={board.lanes.indexOf(l) === 0}
                      onClick={() => dispatch({ type: "lane-order", lane: l.id, direction: -1 })}
                    >
                      Earlier lane {l.model}
                    </button>
                    <button
                      className="cv-button"
                      disabled={board.lanes.indexOf(l) === board.lanes.length - 1}
                      onClick={() => dispatch({ type: "lane-order", lane: l.id, direction: 1 })}
                    >
                      Later lane {l.model}
                    </button>
                    <button
                      className="cv-button"
                      onClick={() => {
                        dispatch({ type: "remove-lane", lane: l.id });
                        setDestination("");
                      }}
                    >
                      Remove lane {l.model}
                    </button>
                    <label>
                      New group name
                      <input
                        className="cv-input"
                        aria-label={`New group name for ${l.model}`}
                        value={groupName}
                        onChange={(e) => setGroupName(e.target.value)}
                      />
                    </label>
                    <button
                      className="cv-button"
                      onClick={() =>
                        dispatch({
                          type: "add",
                          lane: l.id,
                          item: {
                            id: crypto.randomUUID(),
                            kind: "group",
                            name: groupName.trim() || "Temporary group",
                            months: [],
                          },
                        })
                      }
                    >
                      Add group to {l.model}
                    </button>
                  </div>
                </details>
              </div>
              <div className="studio-board-cards">
                {l.items.map((item) => (
                  <ItemControls
                    key={item.id}
                    item={item}
                    lane={l}
                    board={board}
                    dispatch={dispatch}
                  />
                ))}
              </div>
            </section>
          ))}
        <p role="status" className="cv-muted">
          {board.notice}
        </p>
      </section>
      {lane && (
        <section className="studio-panel studio-toolbar" aria-label="Chart scope">
          <strong>
            {board.domain} / {lane.model} / {board.metric.toUpperCase()}
          </strong>
          <label>
            Chart model lane
            <select
              className="cv-input"
              value={lane.id}
              aria-label="Chart model lane"
              onChange={(e) => {
                dispatch({ type: "active", id: e.target.value });
                setDestination("");
              }}
            >
              {board.lanes
                .filter((l) => l.domain === board.domain)
                .map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.model}
                  </option>
                ))}
            </select>
          </label>
          <button className="cv-button" onClick={() => dispatch({ type: "restore" })}>
            Restore all colours
          </button>
          {colors.map((c) => (
            <button
              className="cv-button"
              key={c}
              aria-pressed={!board.hidden.includes(c)}
              onClick={() => dispatch({ type: "hide", color: c })}
            >
              {c}
            </button>
          ))}
        </section>
      )}
      {lanePreview.isError && !reads.some((q) => q.error === lanePreview.error) && (
        <ApiErrorState error={lanePreview.error} retry={() => void lanePreview.refetch()} />
      )}
      {reads.map((q, i) => (
        <div key={items[i].id}>
          {q.isPending && (
            <LoadingState>
              Loading {lane?.model} / {items[i].name}...
            </LoadingState>
          )}
          {q.isError && (
            <section className="studio-panel">
              <h3>
                {lane?.model} / {items[i].name}
              </h3>
              <ApiErrorState error={q.error} retry={() => void q.refetch()} />
            </section>
          )}
          {q.isSuccess && items[i].kind === "group" && !q.data.group_means.length && (
            <p className="cv-empty">{items[i].name}: No group means returned for these months.</p>
          )}
        </div>
      ))}
      {!!items.length && (
        <BoxStage
          entries={entries}
          monthly
          title={`${lane?.model} / ${board.metric.toUpperCase()} distributions`}
        />
      )}
      {board.domain === "WAVESCAN" && !!items.length && (
        <section aria-label="Monthly profiles">
          <h2>Profiles / DU-WE</h2>
          <label className="studio-focus">
            Profile focus
            <select
              className="cv-input"
              aria-label="Profile focus"
              value={focusedItem?.id ?? ""}
              onChange={(e) => setFocus(e.target.value)}
            >
              {items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.kind === "month" ? monthLabel(item.months[0]) : item.name}
                </option>
              ))}
            </select>
          </label>
          {focusedRead?.data && focusedItem && (
            <MonthlyProfile
              key={`${lane?.id}-${focusedItem.id}`}
              item={focusedItem}
              data={focusedRead.data}
              hidden={board.hidden}
              colors={colors}
            />
          )}
        </section>
      )}
    </div>
  );
}
