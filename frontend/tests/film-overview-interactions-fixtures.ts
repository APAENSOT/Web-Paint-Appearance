import { polishFixture } from "./film-overview-polish-fixtures";

// Explicit returned entries: two dates and repeated nullable entries in one Pass box.
export const interactionsFixture: typeof polishFixture = {
  ...polishFixture,
  boxes: polishFixture.boxes.map((box) =>
    box.color_name === "Absolute / Shadow Black" && box.orient === "H" && box.layer_code === "ECOAT"
      ? {
          ...box,
          out_of_spec: [
            ...box.out_of_spec,
            { ...box.out_of_spec[0], point_code: "LOW-02", measured_date: "2026-08-25" },
          ],
        }
      : box,
  ),
};
