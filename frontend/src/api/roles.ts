import type { components } from "./types";

type Principal = components["schemas"]["Principal"];

export const isViewer = (principal?: Principal) => principal?.roles.includes("viewer") ?? false;
export const isEngineer = (principal?: Principal) => principal?.roles.includes("engineer") ?? false;
export const isAdmin = (principal?: Principal) => principal?.roles.includes("admin") ?? false;
export const mayIngest = (principal?: Principal) => isEngineer(principal) || isAdmin(principal);
export const mayCorrect = (principal?: Principal) => isEngineer(principal) || isAdmin(principal);
// T100-FIX2 (D-100-9): who may change which Film points count. The same
// pair the backend's film-points routes require. Since RO12 `mayIngest` is
// the same pair (the upload role); the two stay separate names on purpose.
export const mayEditFilmPoints = (principal?: Principal) =>
  isEngineer(principal) || isAdmin(principal);
// RO17: the Admin-only point-list actions -- a Wave Scan add that counts in
// completeness, Film tail labels, retiring an alias, switching on the Film
// point rules. Rename, add, retire and restore stay `mayEditFilmPoints`.
export const mayAdminPointLists = (principal?: Principal) => isAdmin(principal);
export const mayEditColorAppearance = (principal?: Principal) =>
  isEngineer(principal) || isAdmin(principal);
export const mayApproveMapping = (principal?: Principal) => isAdmin(principal);
export const maySupersede = (principal?: Principal) => isAdmin(principal);
export const mayManagePlantFiles = (principal?: Principal) => isAdmin(principal);
export const maySeeIntakeNav = (principal?: Principal) =>
  isEngineer(principal) || isAdmin(principal);
export const maySeeAdminNav = (principal?: Principal) => isAdmin(principal);
// Owner decision 2026-10-20: this release has no sign-in; everyone is the shared account.
export const roleLabel = (principal?: Principal) =>
  principal?.auth_source === "open-access" ? "No sign-in" : "Signed in";
