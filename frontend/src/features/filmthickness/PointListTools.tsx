import { Search, X } from "lucide-react";

import { EMPTY_POINT_FILTER, type PointFilter } from "./point-list-filter";
export function PointListTools({
  scope,
  total,
  shown,
  counted,
  filter,
  onChange,
}: {
  scope: string;
  total: number;
  shown: number;
  counted: number;
  filter: PointFilter;
  onChange: (filter: PointFilter) => void;
}) {
  const active = filter.query || filter.counted !== "all" || filter.orientation !== "all";
  return (
    <div className="point-list-tools">
      <div className="point-list-summary" role="status">
        <strong>Inspection points</strong>
        <span>
          {shown} of {total} live points · {counted} counted
        </span>
      </div>
      <div className="point-list-filters">
        <label className="point-list-search">
          <span>Find a point</span>
          <div>
            <Search size={16} aria-hidden="true" />
            <input
              aria-label={`Find a ${scope} point`}
              value={filter.query}
              placeholder="Name, code or point number"
              onChange={(e) => onChange({ ...filter, query: e.target.value })}
            />
          </div>
        </label>
        <label>
          <span>Dashboard use</span>
          <select
            aria-label={`${scope} dashboard use`}
            value={filter.counted}
            onChange={(e) => onChange({ ...filter, counted: e.target.value })}
          >
            <option value="all">All points</option>
            <option value="yes">Counted</option>
            <option value="no">Not counted</option>
          </select>
        </label>
        <label>
          <span>Orientation</span>
          <select
            aria-label={`${scope} point orientation`}
            value={filter.orientation}
            onChange={(e) => onChange({ ...filter, orientation: e.target.value })}
          >
            <option value="all">Horizontal + Vertical</option>
            <option value="H">Horizontal</option>
            <option value="V">Vertical</option>
          </select>
        </label>
        {active && (
          <button
            type="button"
            className="point-filter-clear"
            onClick={() => onChange(EMPTY_POINT_FILTER)}
          >
            <X size={16} aria-hidden="true" /> Clear filters
          </button>
        )}
      </div>
      {shown === 0 && total > 0 && (
        <p>No points match these filters. Clear the filters to see the full list.</p>
      )}
    </div>
  );
}
