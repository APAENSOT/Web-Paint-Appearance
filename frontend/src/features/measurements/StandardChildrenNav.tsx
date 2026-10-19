import { useQuery } from "@tanstack/react-query";
import { meOptions } from "@/api/queries";
import { mayEditFilmPoints } from "@/api/roles";

/**
 * T100-FIX2 (D-100-9): the Film Thickness entry is shown to anyone who can
 * upload -- Engineer or Admin -- because the Points panel behind it is theirs
 * (D-99-4). `canEditFilm` still means "this caller may publish a standard",
 * which `PlantMeasurements.tsx` passes as `isAdmin`; the role for the entry
 * is read here instead of changing that caller. A Viewer stays hidden.
 */
export type StandardNavView = "family" | "film";

export function StandardChildrenNav({
  view,
  onSelect,
  canEditFilm = false,
}: {
  canEditFilm?: boolean;
  view: StandardNavView;
  onSelect: (view: StandardNavView) => void;
}) {
  // Cached by every screen that reads identity, so this costs no request.
  const identity = useQuery(meOptions);
  const showFilm =
    canEditFilm || (identity.isSuccess && mayEditFilmPoints(identity.data.principal));
  return (
    <nav
      aria-label="Standard views"
      className="ml-3 mt-2 space-y-1 border-l border-border pl-3 pb-2"
    >
      {(
        [
          ["family", "Color Family"],
          ...(showFilm ? ([["film", "Film Thickness"]] as const) : []),
        ] as const
      ).map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-pressed={view === id}
          data-testid={`standard-nav-${id}`}
          onClick={() => onSelect(id)}
          className="block min-h-11 w-full rounded-sm px-2 py-2 text-left text-xs text-muted-foreground aria-pressed:bg-[var(--primary-soft)] aria-pressed:font-semibold aria-pressed:text-foreground"
        >
          {label}
        </button>
      ))}
    </nav>
  );
}
