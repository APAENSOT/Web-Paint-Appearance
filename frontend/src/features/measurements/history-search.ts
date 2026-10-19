import { parseShared, type SharedBench } from "./comparison-bench";

export type PlantSearch = {
  dataDomain?: "wavescan" | "film" | "both";
  dataView?: "upload" | "history";
  /** Legacy Model/Point Check links remain supported under Model Detail. */
  standardView?: "family" | "model" | "film" | "points";
  modelView?: "model" | "point-check" | "colours" | "inspection";
  file?: string;
  sheet?: number;
  month?: string;
  model?: string;
  color?: string;
  week?: number;
  cardModel?: string;
  cardColor?: string;
  vehicle?: string;
  paint?: "film";
  filmMonth?: string;
  filmModel?: string;
  filmColor?: string;
  filmColors?: string[];
  filmWeek?: number;
  filmCardModel?: string;
  filmCardColor?: string;
  filmVehicle?: string;
  /** Comparison bench shared by link; opens the Comparison display. */
  compare?: SharedBench;
};

export function parsePlantSearch(search: Record<string, unknown>): PlantSearch {
  const text = (value: unknown) =>
    typeof value === "string" && value.length > 0 ? value : undefined;
  const hash = (value: unknown) =>
    typeof value === "string" && /^[0-9a-f]{64}$/.test(value) ? value : undefined;
  // RO18 (B4): week 0 is the "Day not recorded" group; "" and null are no week.
  const week = (value: unknown) => {
    const n = typeof value === "string" && value.trim() ? Number(value) : value;
    return typeof n === "number" && Number.isInteger(n) && n >= 0 && n <= 5 ? n : undefined;
  };
  const colours = Array.isArray(search.filmColors)
    ? [
        ...new Set(
          search.filmColors.filter(
            (value): value is string => typeof value === "string" && value.trim().length > 0,
          ),
        ),
      ]
    : [];
  return {
    dataDomain:
      search.dataDomain === "wavescan" ||
      search.dataDomain === "film" ||
      search.dataDomain === "both"
        ? search.dataDomain
        : undefined,
    dataView:
      search.dataView === "upload" || search.dataView === "files"
        ? "upload"
        : search.dataView === "history" || search.dataView === "measurements"
          ? "history"
          : undefined,
    standardView:
      search.standardView === "model" ||
      search.standardView === "family" ||
      search.standardView === "film" ||
      search.standardView === "points"
        ? search.standardView
        : undefined,
    ...(search.modelView === "model" ||
    search.modelView === "point-check" ||
    search.modelView === "colours" ||
    search.modelView === "inspection"
      ? { modelView: search.modelView }
      : {}),
    file: hash(search.file),
    sheet:
      Number.isSafeInteger(Number(search.sheet)) && Number(search.sheet) > 0
        ? Number(search.sheet)
        : undefined,
    month:
      typeof search.month === "string" && /^\d{4}-\d{2}$/.test(search.month)
        ? search.month
        : undefined,
    model: text(search.model),
    color: text(search.color),
    cardModel: text(search.cardModel),
    cardColor: text(search.cardColor),
    week: week(search.week),
    vehicle: hash(search.vehicle),
    paint: search.paint === "film" ? "film" : undefined,
    filmMonth:
      typeof search.filmMonth === "string" && /^\d{4}-(0[1-9]|1[0-2])$/.test(search.filmMonth)
        ? search.filmMonth
        : undefined,
    filmModel: text(search.filmModel),
    filmColor: text(search.filmColor),
    filmColors: colours.length ? colours : undefined,
    // T108 (D-108-3): Film's own week card params, read exactly as T105
    // reads WaveScan's -- they are not filters, so a card never sets one.
    filmWeek: week(search.filmWeek),
    filmCardModel: text(search.filmCardModel),
    filmCardColor: text(search.filmCardColor),
    filmVehicle: hash(search.filmVehicle),
    compare: parseShared(search.compare),
  };
}

/**
 * RO13 (F8): say that the two domains name models differently only when this
 * plant's month shows it -- some Film model is not a Wave Scan model -- and
 * name the models found.
 */
export function modelVocabularyNote(wave?: string[], film?: string[]): string | null {
  if (!wave?.length || !film?.length) return null;
  const filmOnly = film.filter((model) => !wave.includes(model));
  if (filmOnly.length === 0) return null;
  const waveOnly = wave.filter((model) => !film.includes(model));
  return `Model and colour filter both lists. Wave Scan and Film name models differently (Film: ${filmOnly.join(", ")}; Wave Scan: ${waveOnly.join(", ") || "none other"}), so a choice from one vocabulary leaves the other list empty.`;
}
