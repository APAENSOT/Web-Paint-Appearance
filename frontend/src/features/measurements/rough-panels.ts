/**
 * T94: the rough-panel question's state and copy. No JSX -- the cell that
 * draws it is `RoughPanelCell.tsx`, the same split `held-alias.ts` and
 * `HeldAliasConfirmation.tsx` already use.
 *
 * A panel label whose name -- leading number dropped -- does not identify
 * exactly one panel of that model is **rough** (D-94-1). It is never
 * "Ready", whatever the catalogue holds (D-94-2), and the question about it
 * belongs **in the row that carries it**, highlighted, with the long name we
 * propose already selected and one click to accept (D-94-3). Not below the
 * table. Not in a dialog: `PanelMatchDialog` stays for whole-set work and is
 * not the answer to this.
 *
 * Nothing here decides anything: the proposal, the colour, the reason and
 * the choosable list all come from the worksheet read (`rough_panels`), and
 * a pair is only ever sent because a person pressed a button (D-94-6).
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, refreshActiveMeasurements, refreshWorksheet } from "@/api/queries";
import type { components } from "@/api/types";

type Sheet = components["schemas"]["WorksheetSheetOut"];
export type RoughPanel = components["schemas"]["RoughPanelOut"];
export type PanelPair = { raw_zone_text: string; zone_code: string };

export const ROUGH_PANEL_COPY = {
  heading: "Some panel names do not say which panel they are",
  explain:
    "A name like 01HOOD fits five hoods, so it is never added on its own - not even " +
    "when the list holds a panel spelled exactly like it. Confirm the panel in the " +
    "highlighted row below and the reading loads under that panel's long name.",
  confirm: "Confirm",
  choose: "Choose panel",
  ours: " (we think this one)",
  // T114 (D-114-5): beyond the plant's standard list, added on Point Check.
  extra: " · extra",
} as const;

/** Normalised the same way the backend normalises an alias: trim + fold. */
export function panelKey(label: string | null | undefined): string {
  return (label ?? "").trim().toLowerCase();
}

/**
 * `{normalised panel label: its question}` for one tab.
 *
 * One sheet can carry two models writing the same spellings; the first entry
 * wins, exactly as the backend's own table does, because the question and
 * the answer are the same either way.
 */
export function roughByLabel(sheet: Sheet): Map<string, RoughPanel> {
  const out = new Map<string, RoughPanel>();
  for (const panel of sheet.rough_panels ?? []) {
    const key = panelKey(panel.raw_zone_text);
    if (!out.has(key)) out.set(key, panel);
  }
  return out;
}

/** Every rough panel still waiting for an answer on this tab. */
export function pendingPanels(sheet: Sheet): RoughPanel[] {
  return [...roughByLabel(sheet).values()].filter((panel) => !panel.confirmed_zone_code);
}

/**
 * The pairs the one click sends: every pending panel that already carries the
 * panel we propose (D-94-6). A panel with no proposal is left out - there is
 * nothing pre-filled to accept, and the person picks it themselves.
 */
export function prefilledPairs(sheet: Sheet): PanelPair[] {
  return pendingPanels(sheet)
    .filter((panel) => panel.proposed_zone_code)
    .map((panel) => ({
      raw_zone_text: panel.raw_zone_text,
      zone_code: panel.proposed_zone_code as string,
    }));
}

export function useRoughPanels({
  sheet,
  plant,
  fileHash,
}: {
  sheet: Sheet;
  plant: string;
  fileHash: string;
}) {
  const client = useQueryClient();
  // What the person has changed a row's select to, before they confirm it.
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const byLabel = roughByLabel(sheet);
  const pending = pendingPanels(sheet);
  const prefilled = prefilledPairs(sheet);

  const confirm = useMutation({
    mutationFn: (pairs: PanelPair[]) =>
      api().confirmPanels(plant, fileHash, { load_id: sheet.load_id, pairs }),
    retry: false,
    onSuccess: async () => {
      setChosen({});
      await refreshWorksheet(client, plant, fileHash);
      await refreshActiveMeasurements(client);
    },
  });

  return {
    byLabel,
    pending,
    prefilled,
    confirm,
    loadId: sheet.load_id,
    /** The panel this row currently offers: the person's pick, else ours. */
    selected: (panel: RoughPanel): string =>
      chosen[panelKey(panel.raw_zone_text)] ??
      panel.confirmed_zone_code ??
      panel.proposed_zone_code ??
      "",
    choose: (panel: RoughPanel, zone: string) =>
      setChosen((was) => ({ ...was, [panelKey(panel.raw_zone_text)]: zone })),
    /** The question this row carries, or undefined when it carries none. */
    questionFor: (label: string | null | undefined): RoughPanel | undefined =>
      byLabel.get(panelKey(label)),
    acceptAll: () => {
      if (prefilled.length) confirm.mutate(prefilled);
    },
  };
}

export type RoughPanels = ReturnType<typeof useRoughPanels>;
