import { ComparisonPicker, ComparisonTray } from "./ComparisonPicker";
import { ComparisonMatrix } from "./ComparisonMatrix";
import type { ComparisonSession } from "./useComparisonVehicles";
import type { Dispatch } from "react";
import type { Board, BoardAction } from "./comparison-board";
import { ComparisonStudio } from "./ComparisonStudio";
import { VehicleStudio } from "./VehicleStudio";
import "./comparison-vehicles.css";
export function ComparisonWorkspace({
  code,
  session,
  board,
  dispatchBoard,
}: {
  code: string;
  months: string[];
  onMonthsChange: (months: string[]) => void;
  session: ComparisonSession;
  board: Board;
  dispatchBoard: Dispatch<BoardAction>;
}) {
  return (
    <div className="cv-workspace">
      <div className="panel cv-modes" role="group" aria-label="Comparison mode">
        {(["months", "vehicles"] as const).map((mode) => (
          <button
            className="cv-button"
            key={mode}
            aria-pressed={session.state.mode === mode}
            onClick={() => session.dispatch({ type: "mode", mode })}
          >
            {mode === "months" ? "Months" : "Vehicles"}
          </button>
        ))}
        <p className="cv-muted">
          {session.state.mode !== "vehicles"
            ? "Temporary comparison from measured months"
            : "Compare raw measurements at matching locations"}
        </p>
      </div>
      {session.state.mode === "months" ? (
        <ComparisonStudio
          key={`${code}-${board.domain}`}
          code={code}
          board={board}
          dispatch={dispatchBoard}
        />
      ) : (
        <>
          <ComparisonPicker session={session} />
          <ComparisonTray session={session} />
          <ComparisonMatrix session={session} />
          <VehicleStudio code={code} session={session} />
        </>
      )}
    </div>
  );
}
