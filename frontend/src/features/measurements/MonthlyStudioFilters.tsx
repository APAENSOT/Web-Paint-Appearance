import type { Dispatch } from "react";
import type { Board, BoardAction } from "./comparison-board";
export function MonthlyStudioFilters({ board }: { board: Board; dispatch: Dispatch<BoardAction> }) {
  return (
    <section aria-label="Monthly comparison scope" className="space-y-3 p-4 text-xs">
      <strong>
        {board.domain === "WAVESCAN" ? "WaveScan" : "Film Thickness"} / {board.metric.toUpperCase()}
      </strong>
      <p className="text-muted-foreground">
        Choose models, measured months and visible colours in Months. Groups are temporary and
        remain separate by model.
      </p>
    </section>
  );
}
