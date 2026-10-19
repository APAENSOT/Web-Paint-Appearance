import type { components } from "@/api/types";
export type PreviewInput = components["schemas"]["ComparisonMonthlyPreviewIn"];
export type Preview = components["schemas"]["ComparisonMonthlyPreviewOut"];
export interface BoardItem {
  id: string;
  kind: "month" | "group";
  name: string;
  months: string[];
}
export interface ModelLane {
  id: string;
  domain: PreviewInput["domain"];
  model: string;
  items: BoardItem[];
}
export interface Board {
  lanes: ModelLane[];
  active: string;
  domain: PreviewInput["domain"];
  metric: PreviewInput["metric"];
  hidden: string[];
  notice: string;
}
export const initialBoard = (): Board => ({
  lanes: [],
  active: "",
  domain: "WAVESCAN",
  metric: "cf",
  hidden: [],
  notice: "",
});
export const laneMonths = (lane: ModelLane) => [
  ...new Set(lane.items.flatMap((item) => item.months)),
];
export type BoardAction =
  | { type: "domain"; domain: PreviewInput["domain"] }
  | { type: "metric"; metric: PreviewInput["metric"] }
  | { type: "lane"; lane: ModelLane }
  | { type: "lane-order"; lane: string; direction: -1 | 1 }
  | { type: "remove-lane"; lane: string }
  | { type: "active"; id: string }
  | { type: "add"; lane: string; item: BoardItem }
  | { type: "add-member"; lane: string; id: string; month: string }
  | { type: "remove" | "dissolve"; lane: string; id: string }
  | { type: "rename"; lane: string; id: string; name: string }
  | { type: "reorder"; lane: string; id: string; direction: -1 | 1 }
  | { type: "member-order"; lane: string; id: string; month: string; direction: -1 | 1 }
  | { type: "move"; lane: string; id: string; month: string; targetLane: string; target: string }
  | { type: "hide"; color: string }
  | { type: "restore" };
function reorder<T>(items: T[], index: number, direction: number): T[] {
  const to = index + direction;
  if (index < 0 || to < 0 || to >= items.length) return items;
  const next = [...items];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}
export function boardReducer(state: Board, action: BoardAction): Board {
  if (action.type === "lane-order")
    return {
      ...state,
      lanes: reorder(
        state.lanes,
        state.lanes.findIndex((l) => l.id === action.lane),
        action.direction,
      ),
      notice: "Model lane moved.",
    };
  if (action.type === "remove-lane") {
    const lanes = state.lanes.filter((l) => l.id !== action.lane);
    return {
      ...state,
      lanes,
      active:
        state.active === action.lane
          ? (lanes.find((l) => l.domain === state.domain)?.id ?? "")
          : state.active,
      notice: "Model lane removed.",
    };
  }
  if (action.type === "domain")
    return {
      ...state,
      domain: action.domain,
      metric: action.domain === "WAVESCAN" ? "cf" : "ecoat",
      hidden: [],
      active: state.lanes.find((l) => l.domain === action.domain)?.id ?? "",
    };
  if (action.type === "metric") return { ...state, metric: action.metric };
  if (action.type === "active") return { ...state, active: action.id, hidden: [] };
  if (action.type === "hide")
    return {
      ...state,
      hidden: state.hidden.includes(action.color)
        ? state.hidden.filter((c) => c !== action.color)
        : [...state.hidden, action.color],
    };
  if (action.type === "restore") return { ...state, hidden: [] };
  if (action.type === "lane")
    return state.lanes.some((l) => l.id === action.lane.id)
      ? { ...state, active: action.lane.id }
      : {
          ...state,
          lanes: [...state.lanes, action.lane],
          active: action.lane.id,
          hidden: [],
          notice: `Added ${action.lane.model} lane.`,
        };
  if (action.type === "move" && action.lane !== action.targetLane)
    return { ...state, notice: "Months cannot move across model lanes. The board is unchanged." };
  const lanes = state.lanes.map((lane) => {
    if (lane.id !== action.lane) return lane;
    let items = lane.items;
    if (action.type === "add")
      items = [...items, { ...action.item, months: [...new Set(action.item.months)] }];
    if (action.type === "add-member")
      items = items.map((i) =>
        i.id === action.id && i.kind === "group"
          ? { ...i, months: [...new Set([...i.months, action.month])] }
          : i,
      );
    if (action.type === "remove") items = items.filter((i) => i.id !== action.id);
    if (action.type === "rename")
      items = items.map((i) => (i.id === action.id ? { ...i, name: action.name } : i));
    if (action.type === "reorder")
      items = reorder(
        items,
        items.findIndex((i) => i.id === action.id),
        action.direction,
      );
    if (action.type === "member-order")
      items = items.map((i) =>
        i.id === action.id
          ? { ...i, months: reorder(i.months, i.months.indexOf(action.month), action.direction) }
          : i,
      );
    if (action.type === "dissolve")
      items = items.flatMap((i) =>
        i.id === action.id
          ? i.months.map((month, n) => ({
              id: `${i.id}-${n}`,
              kind: "month" as const,
              name: month,
              months: [month],
            }))
          : [i],
      );
    if (action.type === "move") {
      const source = items.find((i) => i.id === action.id);
      const target = items.find((i) => i.id === action.target && i.kind === "group");
      if (!source?.months.includes(action.month) || (action.target && !target) || source === target)
        return lane;
      items = items
        .map((i) =>
          i.id === action.id
            ? { ...i, months: i.months.filter((m) => m !== action.month) }
            : i.id === action.target
              ? { ...i, months: [...new Set([...i.months, action.month])] }
              : i,
        )
        .filter((i) => i.months.length || i.kind === "group");
      if (!action.target)
        items = [
          ...items,
          {
            id: `${source.id}-out-${action.month}`,
            kind: "month",
            name: action.month,
            months: [action.month],
          },
        ];
    }
    return { ...lane, items };
  });
  return {
    ...state,
    lanes,
    notice: action.type === "move" ? `Moved ${action.month}.` : `Board updated: ${action.type}.`,
  };
}

export function monthLabel(month: string) {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-US", { month: "short", year: "numeric" });
}
