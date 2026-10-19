import type { components } from "../src/api/types";

export const workspaceMeta: components["schemas"]["MetaResponse"] = {
  plants: [
    {
      plant_code: "AAT",
      plant_name: "AutoAlliance Thailand",
      country: "Thailand",
      is_active: true,
    },
    { plant_code: "FVL", plant_name: "Ford Vietnam", country: "Vietnam", is_active: true },
  ],
  models: [],
  colors: [],
  checkzones: [],
  grading_available: false,
  unmapped_color_count: 21,
};

export const catalogueFixture: components["schemas"]["CatalogueOut"] = {
  families: [
    {
      family_code: "MS",
      family_name: "Medium Solids",
      display_order: 5,
      ford_h: 65,
      ford_v: 52,
      min_h: 58,
      min_v: 45,
      effective_from: "2020-01-01",
      plants: [
        { plant_code: "AAT", plant_specific: false, ford_h: 65, ford_v: 52, min_h: 58, min_v: 45 },
        { plant_code: "FTM", plant_specific: true, ford_h: 70, ford_v: 54, min_h: 62, min_v: 47 },
        { plant_code: "FVL", plant_specific: false, ford_h: 65, ford_v: 52, min_h: 58, min_v: 45 },
        { plant_code: "SAP", plant_specific: false, ford_h: 65, ford_v: 52, min_h: 58, min_v: 45 },
      ],
    },
  ],
  colors: [
    {
      color_name: "Ignite Orange",
      color_group: null,
      plants: [
        { plant_code: "AAT", is_offered: true, family_code: "MS", family_name: "Medium Solids" },
        { plant_code: "FTM", is_offered: true, family_code: "MS", family_name: "Medium Solids" },
        { plant_code: "FVL", is_offered: true, family_code: "MS", family_name: "Medium Solids" },
        { plant_code: "SAP", is_offered: true, family_code: "MM", family_name: "Medium Metallics" },
      ],
    },
  ],
  series: [
    {
      series_code: "P703",
      models: [
        {
          model_code: "P703 DBL RANGER",
          body_style: "Pickup",
          expected_zone_count: 32,
          plants: [
            { plant_code: "AAT", is_offered: true },
            { plant_code: "FTM", is_offered: true },
            { plant_code: "FVL", is_offered: true },
            { plant_code: "SAP", is_offered: true },
          ],
        },
      ],
    },
  ],
};

export const measurement: components["schemas"]["MeasurementOut"] = {
  measurement_id: 41,
  measured_date: "2026-09-13",
  date_is_month_only: false,
  plant: "AAT",
  model: "P703",
  checkzone: "RRHOOD",
  color: "White",
  tolerance_group: "Horizontal",
  paintline: "1",
  serial_no: "T09-TEST",
  lw: "3.7",
  sw: "4.2",
  cf: "62",
  doi: "80",
  du: "1",
  wa: "1",
  wb: "2",
  wc: "3",
  wd: "4",
  we: "5",
  b: "0.5",
  load_id: 123,
  source_sheet: "Review1",
  source_row: 2,
  loaded_at: "2026-09-13T00:00:00Z",
  corrects_measurement_id: null,
  correction_reason: null,
};

export const cleanReview: components["schemas"]["BatchReviewOut"] = {
  batch: {
    fixture_verified: true,
    load_id: 123,
    source_file: "review.xlsx",
    source_sheet: "Review1",
    plant_code: "AAT",
    file_hash: "0".repeat(64),
    status: "PENDING_REVIEW",
    counts: {
      rows_in_file: 1,
      rows_loaded: 1,
      rows_duplicate: 0,
      rows_rejected: 0,
      rows_quarantine: 0,
      balanced: true,
    },
    started_at: "2026-09-12T00:00:00Z",
    finished_at: "2026-09-12T00:00:01Z",
    loaded_by: null,
    notes: null,
    superseded_by: null,
    template_fingerprint: null,
    job: {
      status: "DONE",
      attempts: 1,
      last_error: null,
      enqueued_at: "2026-09-12T00:00:00Z",
      started_at: "2026-09-12T00:00:00Z",
      finished_at: "2026-09-12T00:00:01Z",
    },
  },
  reject_reasons: {},
  unidentified_rows: 0,
  staged_rows: 1,
  review_rows: 1,
  committable: true,
  held_labels: [],
};

export const identity: components["schemas"]["MeResponse"] = {
  principal: {
    entra_oid: "00000000-0000-0000-0000-000000000000",
    user_id: null,
    upn: "test@localhost",
    display_name: "Test session",
    roles: ["engineer"],
    auth_source: "dev-bypass",
  },
  plant_scope: null,
  plant_scope_note: "Provisional all-plant visibility",
  environment: "development",
};
