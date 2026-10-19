import type { components } from "@/api/types";
import { filmWarningLabel } from "@/features/filmthickness/film-status";
export type Profile = components["schemas"]["MonthlyProfile"];
export type PointRead = components["schemas"]["MonthlyPointsOut"];
export function pointStatusLabel(status: string, domain: "wavescan" | "film", layer?: string) {
  return (
    (
      {
        PASS: "Pass",
        WARNING: domain === "film" ? filmWarningLabel(layer) : "Warning",
        FAIL: "Fail",
        OVER: "Over",
        NO_DATA: "No data",
        UNCLASSIFIED: "No Standard",
      } as Record<string, string>
    )[status] ?? status
  );
}
export type Scope = {
  query: string;
  models: string[];
  colors: string[];
  family: string;
  measuredOnly: boolean;
};
export function filterProfiles(items: Profile[], scope: Scope) {
  const query = scope.query.trim().toLocaleLowerCase();
  return items
    .filter(
      (p) =>
        (!scope.models.length || scope.models.includes(p.model_code)) &&
        (!scope.colors.length || scope.colors.includes(p.color_name)) &&
        (!scope.family || p.family_name === scope.family) &&
        (!scope.measuredOnly || p.sample_count > 0) &&
        (!query ||
          `${p.model_code} ${p.color_name} ${p.family_name ?? ""}`
            .toLocaleLowerCase()
            .includes(query)),
    )
    .sort(
      (a, b) =>
        Number(b.sample_count > 0) - Number(a.sample_count > 0) ||
        a.model_code.localeCompare(b.model_code) ||
        a.color_name.localeCompare(b.color_name),
    );
}
const PHOTOS: Record<string, { src: string; note?: string }> = {
  "P703 DBL RANGER": { src: "ranger.png" },
  "P703 DBL RAPTOR": { src: "raptor.png" },
  "P703 DBL SUPER DUTY": { src: "super-duty.png" },
  U704: { src: "everest.png" },
  V363: { src: "transit.png" },
  "J73 DBL": { src: "amarok.png" },
  "P703 SGL": { src: "ranger.png", note: "Ranger reference · Single cab inspection body" },
  "P703 RAPCAP": { src: "ranger.png", note: "Ranger reference · RAPCAP inspection body" },
  CX743: { src: "territory.png" },
};
export const profilePhoto = (model: string) => PHOTOS[model] ?? null;
export function sampleRows(samples: PointRead["samples"]) {
  return samples.flatMap((sample, i) =>
    (sample.readings.length ? sample.readings : [null]).map((reading, j) => ({
      sample: i + 1,
      reading: j + 1,
      vehicleId: sample.vehicle_id,
      date: sample.measured_date,
      identity:
        sample.serial_no ||
        sample.car_label ||
        sample.job_nos?.join(", ") ||
        "Identity not supplied",
      value: reading?.value ?? null,
      source: reading,
    })),
  );
}
