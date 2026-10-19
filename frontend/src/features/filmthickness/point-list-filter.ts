export type PointFilter = { query: string; counted: string; orientation: string };
export const EMPTY_POINT_FILTER: PointFilter = { query: "", counted: "all", orientation: "all" };
export function matchesPointFilter(
  filter: PointFilter,
  point: {
    point_no: number;
    code: string;
    label: string | null;
    counted: boolean;
    orientation: string | null;
  },
) {
  return (
    `${point.point_no} ${point.label ?? ""} ${point.code}`
      .toLowerCase()
      .includes(filter.query.trim().toLowerCase()) &&
    (filter.counted === "all" || point.counted === (filter.counted === "yes")) &&
    (filter.orientation === "all" || point.orientation === filter.orientation)
  );
}
