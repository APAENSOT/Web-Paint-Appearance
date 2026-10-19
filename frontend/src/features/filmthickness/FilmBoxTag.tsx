import type { components } from "@/api/types";

/** The server's tag. `undefined` is `WorksheetSheetOut.film_box` unsent --
 * the same "nothing to say" as null. */
export type FilmBox = components["schemas"]["FilmVehicleOut"]["box"] | undefined;

/** T103 (D-103-1): the server's tag in the words the screen shows.
 *
 * The rule is the server's -- `ref_plant_film_point` decides where a list's
 * box section starts, and a plant whose list names no stop sends `null`.
 * Nothing here looks at a model, a panel or a point: null renders nothing,
 * because a tag the data cannot support is worse than no tag.
 */
export function filmBoxLabel(box: FilmBox): string | null {
  if (box === "box") return "Box";
  if (box === "no_box") return "No box";
  return null;
}

export function FilmBoxTag({ box, label }: { box: FilmBox; label?: string }) {
  const words = filmBoxLabel(box);
  if (!words) return null;
  return (
    <span
      data-testid={`film-box-${box}`}
      aria-label={label ? `${label}: ${words}` : undefined}
      className="inline-block rounded-sm border border-border px-2 py-0.5 text-[10px] font-semibold"
    >
      {words}
    </span>
  );
}
