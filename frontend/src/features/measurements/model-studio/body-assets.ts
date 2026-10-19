/** Visual bodies assigned to the exact Standard names confirmed by the owner.
 * These are appearance assets, not database point-surface registrations.
 */
export const PREPARED_BODY_VERSION = "20261013-repair-3";
export const CX743_BODY_VERSION = "20261014-cx743-reference-2";
export type BodyAsset = {
  id: string;
  label: string;
  url: string;
  note: string;
  assetVersion: string;
};
const body = (
  id: string,
  label: string,
  note: string,
  version = PREPARED_BODY_VERSION,
): BodyAsset => ({
  id,
  label,
  note,
  assetVersion: `${id}@${version}`,
  url: `/models/prepared/${id}-body.glb?v=${version}`,
});
export const PREPARED_BODIES: Readonly<Record<string, BodyAsset>> = {
  "P703 SGL": body(
    "ranger-sgl",
    "Ranger single cab",
    "Short cab with a closed rear pillar and an undistorted pickup bed.",
  ),
  "P703 RAPCAP": body(
    "ranger-rapcap",
    "Ranger RAPCAP",
    "Short access doors without exterior rear handles; original bed wheel openings.",
  ),
  "P703 DBL RAPTOR": body(
    "ranger-raptor",
    "Ranger Raptor",
    "Simplified wide Ranger-derived shell with aligned panel seams.",
  ),
  "P703 DBL SUPER DUTY": body(
    "super-duty",
    "Ranger Super Duty",
    "Simplified Ranger-derived double cab, guided by the supplied body references.",
  ),
  U704: body(
    "everest",
    "Everest",
    "Sunroof opening and repaired lower liftgate. Lamps and glass remain open.",
  ),
  V363: body(
    "transit",
    "Transit",
    "Passenger window apertures, repaired lower body and open front lamp areas.",
  ),
  "J73 DBL": body(
    "amarok",
    "Amarok",
    "Supplied 2011 exterior shell with recovered pillars and loose front fragments removed.",
  ),
  CX743: body(
    "territory",
    "Territory",
    "Territory body panels from the supplied 2022 model, with four doors, restored window pillars and panoramic roof opening. Visual inspection body, not engineering CAD.",
    CX743_BODY_VERSION,
  ),
};
