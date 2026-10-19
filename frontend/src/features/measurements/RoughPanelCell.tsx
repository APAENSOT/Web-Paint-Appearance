/**
 * T94 (D-94-3): the rough-panel question, drawn inside the table row's own
 * "Resolved zone" cell.
 *
 * That placement is the decision. T90 built the same control in
 * `PanelMatchDialog` -- a separate dialog reached from a list *below* the
 * table -- so the screen the owner actually reviews never got it. This is a
 * cell of `ConfirmWorksheet`'s table and nothing else, which is why a
 * browser spec can assert the confirmation is in the row.
 */
import type { components } from "@/api/types";
import { ApiErrorState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";
import { ROUGH_PANEL_COPY, type RoughPanel, type RoughPanels } from "./rough-panels";

export function RoughPanelCell({
  panel,
  row,
  rough,
}: {
  panel: RoughPanel;
  row: components["schemas"]["WorksheetRowOut"];
  rough: RoughPanels;
}) {
  const value = rough.selected(panel);
  const selectId = `rough-panel-${rough.loadId}-${row.source_row}`;
  return (
    <div className="min-w-56 space-y-1" data-testid={`rough-panel-row-${panel.raw_zone_text}`}>
      <label className="block text-xs font-medium" htmlFor={selectId}>
        Which panel is {panel.raw_zone_text}?
      </label>
      <select
        id={selectId}
        data-testid={`rough-panel-select-${panel.raw_zone_text}`}
        className="min-h-11 w-full rounded-md border border-border bg-background px-2 text-xs"
        value={value}
        disabled={rough.confirm.isPending}
        onChange={(event) => rough.choose(panel, event.target.value)}
      >
        <option value="">{ROUGH_PANEL_COPY.choose}</option>
        {panel.choosable.map((zone) => (
          <option key={zone} value={zone}>
            {zone}
            {zone === panel.proposed_zone_code ? ROUGH_PANEL_COPY.ours : ""}
            {/* T114 (D-114-5): an extra point says so in the picker. */}
            {(panel.extra_choices ?? []).includes(zone) ? ROUGH_PANEL_COPY.extra : ""}
          </option>
        ))}
      </select>
      <Button
        className="min-h-11 w-full"
        data-testid={`rough-panel-confirm-${panel.raw_zone_text}`}
        disabled={!value || rough.confirm.isPending}
        onClick={() =>
          rough.confirm.mutate([{ raw_zone_text: panel.raw_zone_text, zone_code: value }])
        }
      >
        {ROUGH_PANEL_COPY.confirm} {value}
      </Button>
      <p className="text-xs" data-rough-attention={panel.attention}>
        {panel.operator_message}
      </p>
      {rough.confirm.isError && <ApiErrorState error={rough.confirm.error} />}
    </div>
  );
}
