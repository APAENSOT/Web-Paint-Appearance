import { buildMeasurementQuery, type MeasurementListFilters } from "./measurement-query";
import { queryOptions, type QueryClient } from "@tanstack/react-query";
import type { components } from "./types";

export const pointProfileOptions = (plant: string, model: string, domain: "wavescan" | "film") =>
  queryOptions({
    queryKey: ["point-profile", plant.toUpperCase(), model, domain],
    queryFn: ({ signal }) => api().pointProfile(plant.toUpperCase(), model, domain, signal),
    retry: false,
    enabled: Boolean(model),
  });
import {
  createApiClient,
  type AnalysisReportQuery,
  type AssistantQuery,
  type ComparisonVehiclesQuery,
  type ComparisonPointsQuery,
  type ComparisonMonthlyPreviewBody,
  type ComparisonVehicleVisualsQuery,
  type HistoryFacetsQuery,
  type ImgColorsQuery,
  type ImgOverviewQuery,
  type HistoryPointsQuery,
  type HistorySummariesQuery,
  type HistoryVehiclesQuery,
  type FilmOverviewQuery,
  type FilmFacetsQuery,
  type FilmVehiclesQuery,
  type FilmSummariesQuery,
  type PointDomain,
  type PreviewQuery,
  type WavescanOverviewQuery,
  type WorkbookRowsQuery,
  type MonthlyProfilesQuery,
  type MonthlyPointsQuery,
  type MonthlyPointStatusesQuery,
} from "./client";
import { batchPollInterval } from "./batch-state";

// Construct inside queryFn so configuration errors reach the local error UI.
// No base URL: the API is served from this page's own origin (one Cloud Run service).
export const api = () =>
  createApiClient(import.meta.env.VITE_API_BASE_URL || window.location.origin);
export const monthlyProfilesOptions = (plant: string, query: MonthlyProfilesQuery) =>
  queryOptions({
    queryKey: ["monthly-detail", "profiles", plant, query],
    queryFn: ({ signal }) => api().monthlyProfiles(plant, query, signal),
    retry: false,
  });
export const monthlyPointsOptions = (plant: string, query: MonthlyPointsQuery) =>
  queryOptions({
    queryKey: ["monthly-detail", "points", plant, query],
    queryFn: ({ signal }) => api().monthlyPoints(plant, query, signal),
    retry: false,
  });
export const monthlyPointStatusesOptions = (plant: string, query: MonthlyPointStatusesQuery) =>
  queryOptions({
    queryKey: ["monthly-detail", "point-statuses", plant, query],
    queryFn: ({ signal }) => api().monthlyPointStatuses(plant, query, signal),
    retry: false,
  });
export const comparisonVehiclesOptions = (plant: string, query: ComparisonVehiclesQuery) =>
  queryOptions({
    queryKey: ["comparison", "vehicles", plant, query],
    queryFn: ({ signal }) => api().comparisonVehicles(plant, query, signal),
    retry: false,
  });
export const comparisonPointsOptions = (plant: string, query: ComparisonPointsQuery) =>
  queryOptions({
    queryKey: ["comparison", "points", plant, query],
    queryFn: ({ signal }) => api().comparisonPoints(plant, query, signal),
    retry: false,
  });
// This POST computes a temporary read; it does not save or invalidate anything.
export const comparisonMonthlyPreviewOptions = (
  plant: string,
  body: ComparisonMonthlyPreviewBody,
) =>
  queryOptions({
    queryKey: ["comparison", "monthly-preview", plant, body],
    queryFn: ({ signal }) => api().comparisonMonthlyPreview(plant, body, signal),
    retry: false,
  });
export const comparisonVehicleVisualsOptions = (
  plant: string,
  query: ComparisonVehicleVisualsQuery,
) =>
  queryOptions({
    queryKey: ["comparison", "vehicle-visuals", plant, query],
    queryFn: ({ signal }) => api().comparisonVehicleVisuals(plant, query, signal),
    retry: false,
  });
export const meOptions = queryOptions({
  queryKey: ["identity"],
  queryFn: ({ signal }) => api().me(signal),
});
export const metaOptions = queryOptions({
  queryKey: ["metadata"],
  queryFn: ({ signal }) => api().meta(signal),
});
export const catalogueOptions = queryOptions({
  queryKey: ["standards", "catalogue"],
  queryFn: ({ signal }) => api().catalogue(signal),
});
export const colorAppearancesOptions = (plant: string) =>
  queryOptions({
    queryKey: ["color-appearances", plant.toUpperCase()],
    queryFn: ({ signal }) => api().colorAppearances(plant.toUpperCase(), signal),
    retry: false,
  });
/** AR01: Wave Scan <-> Film pairing readiness, counts only. */
/** Overview IMG: eligible measured months, newest first. */
export const imgMonthsOptions = queryOptions({
  queryKey: ["img", "months"],
  queryFn: ({ signal }) => api().imgMonths(signal),
  retry: false,
});
export const imgOverviewOptions = (query: ImgOverviewQuery) =>
  queryOptions({
    queryKey: ["img", "overview", query],
    queryFn: ({ signal }) => api().imgOverview(query, signal),
    retry: false,
  });
/** IMG Color: average CF per plant x colour, ranked by the API. */
export const imgColorsOptions = (query: ImgColorsQuery) =>
  queryOptions({
    queryKey: ["img", "colors", query],
    queryFn: ({ signal }) => api().imgColors(query, signal),
    retry: false,
  });
/** Landing cards, feed sidebar and plant preview: one read, refreshed every minute. */
export const landingStatusOptions = queryOptions({
  queryKey: ["landing", "status"],
  queryFn: ({ signal }) => api().landingStatus(signal),
  refetchInterval: 60_000,
  retry: false,
});
export const pairingReadinessOptions = (plant: string) =>
  queryOptions({
    queryKey: ["analysis", "pairing", plant.toUpperCase()],
    queryFn: ({ signal }) => api().pairingReadiness(plant.toUpperCase(), signal),
    retry: false,
  });
/** AR03: the Analysis & Report sections for one plant month. */
export const analysisReportOptions = (plant: string, query: AnalysisReportQuery) =>
  queryOptions({
    queryKey: ["analysis", "report", plant.toUpperCase(), query],
    queryFn: ({ signal }) => api().analysisReport(plant.toUpperCase(), query, signal),
    retry: false,
  });
/** AR04: one guided answer, asked once; the card keeps it while filters move on. */
export const assistantAnswerOptions = (plant: string, query: AssistantQuery) =>
  queryOptions({
    queryKey: ["analysis", "ask", plant.toUpperCase(), query],
    queryFn: ({ signal }) => api().assistantAnswer(plant.toUpperCase(), query, signal),
    retry: false,
    staleTime: Infinity,
  });
/** AR05: the assistant's question catalog (menu, keywords, slots); static per release. */
export const assistantQuestionsOptions = (plant: string) =>
  queryOptions({
    queryKey: ["analysis", "questions", plant.toUpperCase()],
    queryFn: ({ signal }) => api().assistantQuestions(plant.toUpperCase(), signal),
    retry: false,
    staleTime: Infinity,
  });
/** T112: the Model screen's cards, with live and counted points per domain. */
export const modelPointsOptions = (plant: string) =>
  queryOptions({
    queryKey: ["standards", "model-points", plant.toUpperCase()],
    queryFn: ({ signal }) => api().modelPoints(plant.toUpperCase(), signal),
  });
export const previewOptions = (query: PreviewQuery) =>
  queryOptions({
    queryKey: ["preview", query],
    queryFn: ({ signal }) => api().preview(query, signal),
    retry: false,
  });
export const readinessOptions = queryOptions({
  queryKey: ["readiness"],
  queryFn: ({ signal }) => api().ready(signal),
  retry: false,
});
export const plantCountOptions = (plant: string) =>
  queryOptions({
    queryKey: ["measurements", "count", plant],
    queryFn: ({ signal }) => api().measurements({ plant, limit: 1, offset: 0 }, signal),
    retry: false,
  });
export const attentionOptions = queryOptions({
  queryKey: ["batches", "attention"],
  queryFn: ({ signal }) => api().batches({ limit: 50 }, signal),
  retry: false,
});
export const measurementsOptions = (
  plant: string,
  offset: number,
  filters: MeasurementListFilters = {},
) => {
  const query = buildMeasurementQuery(plant, offset, filters);
  return queryOptions({
    queryKey: ["measurements", query],
    queryFn: ({ signal }) => api().measurements(query, signal),
    retry: false,
  });
};

export const measurementOptions = (id: number) =>
  queryOptions({
    queryKey: ["measurement", id],
    queryFn: ({ signal }) => api().measurement(id, signal),
    retry: false,
  });

export const historyFacetsOptions = (plant: string, query: HistoryFacetsQuery = {}) =>
  queryOptions({
    queryKey: ["history", plant, "facets", query],
    queryFn: ({ signal }) => api().historyFacets(plant, query, signal),
    retry: false,
  });

export const historySummariesOptions = (plant: string, query: HistorySummariesQuery) =>
  queryOptions({
    queryKey: ["history", plant, "summaries", query],
    queryFn: ({ signal }) => api().historySummaries(plant, query, signal),
    retry: false,
  });

export const historyVehiclesOptions = (plant: string, query: HistoryVehiclesQuery) =>
  queryOptions({
    queryKey: ["history", plant, "vehicles", query],
    queryFn: ({ signal }) => api().historyVehicles(plant, query, signal),
    retry: false,
  });

export const historyVehiclePointsOptions = (
  plant: string,
  vehicleId: string,
  query: HistoryPointsQuery = {},
) =>
  queryOptions({
    queryKey: ["history", plant, "vehicles", vehicleId, "points", query],
    queryFn: ({ signal }) => api().historyVehiclePoints(plant, vehicleId, query, signal),
    retry: false,
  });

export const wavescanOverviewOptions = (plant: string, query: WavescanOverviewQuery) =>
  queryOptions({
    queryKey: ["overview", plant, query],
    queryFn: ({ signal }) => api().wavescanOverview(plant, query, signal),
    retry: false,
  });

export const filmOverviewOptions = (plant: string, query: FilmOverviewQuery = {}) =>
  queryOptions({
    queryKey: ["filmthickness", plant, "overview", query],
    queryFn: ({ signal }) => api().filmOverview(plant, query, signal),
    retry: false,
  });

export const filmFacetsOptions = (plant: string, query: FilmFacetsQuery = {}) =>
  queryOptions({
    queryKey: ["filmthickness", plant, "facets", query],
    queryFn: ({ signal }) => api().filmFacets(plant, query, signal),
    retry: false,
  });

export const filmSummariesOptions = (plant: string, query: FilmSummariesQuery) =>
  queryOptions({
    queryKey: ["filmthickness", plant, "summaries", query],
    queryFn: ({ signal }) => api().filmSummaries(plant, query, signal),
    retry: false,
  });

export const filmVehiclesOptions = (plant: string, query: FilmVehiclesQuery) =>
  queryOptions({
    queryKey: ["filmthickness", plant, "vehicles", query],
    queryFn: async ({ signal }) => {
      const first = await api().filmVehicles(plant, { ...query, limit: 200, offset: 0 }, signal);
      const items = [...first.items];
      let offset = first.page.returned;
      while (offset < first.page.total) {
        const next = await api().filmVehicles(plant, { ...query, limit: 200, offset }, signal);
        if (!next.page.returned) throw new Error("Film vehicle pagination stopped early.");
        items.push(...next.items);
        offset += next.page.returned;
      }
      return { ...first, items };
    },
    retry: false,
  });

export const filmVehiclePointsOptions = (plant: string, vehicleId: string) =>
  queryOptions({
    queryKey: ["filmthickness", plant, "points", vehicleId],
    queryFn: ({ signal }) => api().filmVehiclePoints(plant, vehicleId, signal),
    retry: false,
  });

export async function refreshActiveMeasurements(client: QueryClient) {
  // A successful retirement makes old data unsafe even when the next read fails.
  // Cancel pre-mutation reads, invalidate all pages/by-id entries, then clear and refetch.
  for (const queryKey of [
    ["measurements"],
    ["measurement"],
    ["preview"],
    ["history"],
    ["overview"],
  ]) {
    await client.cancelQueries({ queryKey });
    await client.invalidateQueries({ queryKey, refetchType: "none" });
    await client.resetQueries({ queryKey });
  }
}

export const batchesOptions = (offset: number) =>
  queryOptions({
    queryKey: ["batches", offset],
    queryFn: ({ signal }) => api().batches({ offset, limit: 10 }, signal),
  });

export const batchOptions = (id: number) =>
  queryOptions({
    queryKey: ["batch", id],
    queryFn: ({ signal }) => api().batch(id, signal),
    refetchInterval: (query) =>
      batchPollInterval(
        query.state.data?.batch,
        query.state.dataUpdateCount,
        query.state.status === "error",
      ),
    retry: false,
  });

export const workbooksOptions = (plant: string, offset = 0) =>
  queryOptions({
    queryKey: ["workbooks", plant, offset],
    queryFn: ({ signal }) => api().workbooks(plant, { offset, limit: 200 }, signal),
    refetchInterval: (query) =>
      workbookPollInterval(
        query.state.data?.items.flatMap((workbook) => workbook.sheets),
        query.state.dataUpdateCount,
        query.state.status === "error",
      ),
    retry: false,
  });

export const workbookOptions = (plant: string, fileHash: string) =>
  queryOptions({
    queryKey: ["workbook", plant, fileHash],
    queryFn: async ({ signal, client }) => {
      const queryKey = ["workbook", plant, fileHash] as const;
      const previous = client.getQueryData<components["schemas"]["WorkbookDetailOut"]>(queryKey);
      const next = await api().workbook(plant, fileHash, signal);
      await refreshSettledReplayProposals(client, previous?.workbook.sheets, next.workbook.sheets);
      if (
        previous?.workbook.sheets.some(
          (sheet) =>
            sheet.batch.status === "RUNNING" &&
            next.workbook.sheets.find((item) => item.batch.load_id === sheet.batch.load_id)?.batch
              .status !== "RUNNING",
        )
      ) {
        await Promise.all([
          ...["issues", "rows", "history", "vehicles", "points"].map((section) =>
            client.invalidateQueries({ queryKey: ["workbook", plant, fileHash, section] }),
          ),
          // T97 (D-97-5): the review screen reads the worksheet once while
          // the sheet is still RUNNING. This poll already knows when parsing
          // ended, so refresh it here instead of remounting the component.
          client.invalidateQueries({ queryKey: ["worksheet", plant, fileHash] }),
        ]);
      }
      return next;
    },
    refetchInterval: (query) =>
      workbookPollInterval(
        query.state.data?.workbook.sheets,
        query.state.dataUpdateCount,
        query.state.status === "error",
      ),
    retry: false,
  });

// T86/T88: the whole guided panel-match screen in one read. `confirmed` is
// part of the key because confirming a pair re-solves the rest around it
// (D-88-2), so each set of pinned pairs is a different read.
export const panelMatchOptions = (loadId: number, modelCode: string, confirmed: string[] = []) =>
  queryOptions({
    queryKey: ["panel-match", loadId, modelCode, confirmed],
    queryFn: ({ signal }) =>
      api().panelMatch(
        { load_id: loadId, model_code: modelCode, ...(confirmed.length ? { confirmed } : {}) },
        signal,
      ),
    retry: false,
  });

export const worksheetOptions = (plant: string, fileHash: string) =>
  queryOptions({
    queryKey: ["worksheet", plant, fileHash],
    queryFn: ({ signal }) => api().worksheet(plant, fileHash, signal),
    retry: false,
  });

export async function refreshWorksheet(client: QueryClient, plant: string, fileHash: string) {
  await client.invalidateQueries({ queryKey: ["worksheet", plant, fileHash] });
  await refreshPlantWorkbooks(client, plant);
}

export const workbookRowsOptions = (
  plant: string,
  fileHash: string,
  query: WorkbookRowsQuery = { offset: 0, limit: 50 },
) =>
  queryOptions({
    queryKey: ["workbook", plant, fileHash, "rows", query],
    queryFn: ({ signal }) => api().workbookRows(plant, fileHash, query, signal),
    retry: false,
  });

export const workbookIssuesOptions = (plant: string, fileHash: string) =>
  queryOptions({
    queryKey: ["workbook", plant, fileHash, "issues"],
    queryFn: ({ signal }) => api().workbookIssues(plant, fileHash, signal),
    retry: false,
  });

export const workbookHistoryOptions = (plant: string, fileHash: string) =>
  queryOptions({
    queryKey: ["workbook", plant, fileHash, "history"],
    queryFn: ({ signal }) => api().workbookHistory(plant, fileHash, signal),
    retry: false,
  });

export async function refreshPlantWorkbooks(client: QueryClient, plant: string) {
  await client.invalidateQueries({ queryKey: ["workbooks", plant] });
  await client.invalidateQueries({ queryKey: ["workbook", plant] });
}

function workbookPollInterval(
  sheets: components["schemas"]["WorkbookSheetOut"][] | undefined,
  updates: number,
  failed: boolean,
) {
  const running = sheets?.find((sheet) => sheet.batch.status === "RUNNING");
  return batchPollInterval(running?.batch, updates, failed);
}

export async function refreshSettledReplayProposals(
  client: QueryClient,
  previous: components["schemas"]["WorkbookSheetOut"][] | undefined,
  next: components["schemas"]["WorkbookSheetOut"][],
) {
  const nextById = new Map(next.map((sheet) => [sheet.batch.load_id, sheet]));
  const settled = (previous ?? []).filter(
    (sheet) =>
      sheet.batch.status === "RUNNING" &&
      nextById.get(sheet.batch.load_id)?.batch.status !== "RUNNING",
  );
  await Promise.all(
    settled.map((sheet) =>
      client.invalidateQueries({ queryKey: ["proposals", sheet.batch.load_id] }),
    ),
  );
}

export const proposalsOptions = (id: number, offset: number) =>
  queryOptions({
    queryKey: ["proposals", id, offset],
    queryFn: ({ signal }) => api().proposals({ load_id: id, offset, limit: 10 }, signal),
  });

export async function refreshAfterApproval(
  client: QueryClient,
  result: components["schemas"]["ApprovalResult"],
) {
  const replay = result.replay;
  if (replay) {
    const queryKey = ["batch", replay.load_id];
    // Cancel an older review response before enabling T07's RUNNING polling.
    await client.cancelQueries({ queryKey });
    if (replay.status === "RUNNING")
      client.setQueryData<components["schemas"]["BatchReviewOut"]>(
        queryKey,
        (previous) =>
          previous && {
            ...previous,
            committable: false,
            batch: {
              ...previous.batch,
              status: "RUNNING",
              job: previous.batch.job && {
                ...previous.batch.job,
                status: "QUEUED",
                last_error: null,
              },
            },
          },
      );
    await client.invalidateQueries({ queryKey });
  }
  await Promise.all([
    client.invalidateQueries({ queryKey: ["proposals", result.proposal.load_id] }),
    client.invalidateQueries({ queryKey: ["batches"] }),
  ]);
}

// Each inbox is paginated independently; never scan the all-workbooks index.
export const workbookInboxOptions = (
  plant: string,
  inbox: "all" | "needs_attention" | "current_month",
  uploadedMonth?: string,
) =>
  queryOptions({
    queryKey: ["workbooks", plant, inbox, uploadedMonth],
    queryFn: async ({ signal }) => {
      const first = await api().workbooks(
        plant,
        {
          inbox,
          uploaded_month: inbox === "all" ? undefined : uploadedMonth,
          limit: 200,
          offset: 0,
        },
        signal,
      );
      const items = [...first.items];
      let offset = first.page.returned;
      while (offset < first.page.total) {
        const next = await api().workbooks(
          plant,
          {
            inbox,
            uploaded_month: inbox === "all" ? undefined : (first.uploaded_month ?? undefined),
            limit: 200,
            offset,
          },
          signal,
        );
        if (!next.page.returned)
          throw new Error("Inbox pagination stopped before all workbooks were returned.");
        items.push(...next.items);
        offset += next.page.returned;
      }
      return { ...first, items };
    },
    refetchInterval: (query) =>
      workbookPollInterval(
        query.state.data?.items.flatMap((item) => item.sheets),
        query.state.dataUpdateCount,
        query.state.status === "error",
      ),
    retry: false,
  });
export const workbookVehiclesOptions = (plant: string, hash: string, loadId: number) =>
  queryOptions({
    queryKey: ["workbook", plant, hash, "vehicles", loadId],
    queryFn: async ({ signal }) => {
      const first = await api().workbookVehicles(
        plant,
        hash,
        { load_id: loadId, limit: 200, offset: 0 },
        signal,
      );
      const items = [...first.items];
      let offset = first.page.returned;
      while (offset < first.page.total) {
        const next = await api().workbookVehicles(
          plant,
          hash,
          { load_id: loadId, limit: 200, offset },
          signal,
        );
        if (!next.page.returned)
          throw new Error("Vehicle pagination stopped before all sets were returned.");
        items.push(...next.items);
        offset += next.page.returned;
      }
      return { ...first, items };
    },
    retry: false,
  });
export const workbookVehiclePointsOptions = (plant: string, hash: string, vehicleId: string) =>
  queryOptions({
    queryKey: ["workbook", plant, hash, "points", vehicleId],
    queryFn: async ({ signal }) => {
      const first = await api().workbookVehiclePoints(
        plant,
        hash,
        vehicleId,
        { limit: 200, offset: 0 },
        signal,
      );
      const items = [...first.items];
      let offset = first.page.returned;
      while (offset < first.page.total) {
        const next = await api().workbookVehiclePoints(
          plant,
          hash,
          vehicleId,
          { limit: 200, offset },
          signal,
        );
        if (!next.page.returned)
          throw new Error("Point pagination stopped before all points were returned.");
        items.push(...next.items);
        offset += next.page.returned;
      }
      return { ...first, items };
    },
    retry: false,
  });

// T100 (Part C): which Film models this plant has a point list for, and the
// list itself. Two reads, so the model picker does not wait on a table.
export const filmModelsOptions = (plant: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["filmthickness", "models", code],
    queryFn: ({ signal }) => api().filmModels(code, signal),
    retry: false,
  });
};

export const filmPointSettingOptions = (plant: string, model: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["filmthickness", "points", code, model],
    queryFn: ({ signal }) => api().filmPointSetting(code, model, signal),
    retry: false,
    enabled: Boolean(model),
  });
};

export async function refreshFilmPoints(client: QueryClient, plant: string, model: string) {
  // T109: one prefix, because a change to the list reaches more than the
  // list. A counted / H-V change rewrites the dashboard's Hor / Ver for
  // every month (D-99-4); an add or a retire also changes the list's size,
  // which the model picker shows, and a retire changes what a car's point
  // grid says. `model` stays in the signature: the caller names what it
  // changed, and a narrower key here would be the only thing to edit if
  // these reads are ever split.
  void model;
  await client.invalidateQueries({ queryKey: ["filmthickness"] });
  await client.invalidateQueries({
    queryKey: ["point-profile", plant.toUpperCase(), model, "film"],
  });
}

// T114: Point Check's Wave Scan section -- the model picker and one list.
export const wsPointModelsOptions = (plant: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["ws-points", code],
    queryFn: ({ signal }) => api().wsPointModels(code, signal),
    retry: false,
  });
};

export const wsPointListOptions = (plant: string, model: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["ws-points", code, model],
    queryFn: ({ signal }) => api().wsPointList(code, model, signal),
    retry: false,
    enabled: Boolean(model),
  });
};

// RO17 (D-RO17-16): every point's current label at one plant, both domains,
// so any screen can show the plant's word first and the code second.
export const pointLabelsOptions = (plant: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["point-labels", code],
    queryFn: ({ signal }) => api().pointLabels(code, signal),
    retry: false,
    staleTime: 60_000,
  });
};

// RO17 (D-RO17-13): the spellings that resolve to one plant x model's points.
export const pointAliasesOptions = (plant: string, domain: PointDomain, model: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["point-aliases", code, domain, model],
    queryFn: ({ signal }) => api().pointAliases(code, domain, model, signal),
    retry: false,
    enabled: Boolean(model),
  });
};

// RO17 (D-RO17-7): what a counted Wave Scan add would do to stored cars.
export const wsCompletenessImpactOptions = (plant: string, model: string, zoneCode: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["ws-points", code, model, "impact", zoneCode],
    queryFn: ({ signal }) => api().wsCompletenessImpact(code, model, zoneCode, signal),
    retry: false,
    enabled: Boolean(model && zoneCode.trim()),
  });
};

export async function refreshPointLabels(client: QueryClient, plant: string) {
  // RO17: a rename, restore or alias retire shows wherever a point is named.
  const code = plant.toUpperCase();
  await Promise.all([
    client.invalidateQueries({ queryKey: ["point-labels", code] }),
    client.invalidateQueries({ queryKey: ["point-profile", code] }),
    client.invalidateQueries({ queryKey: ["point-aliases", code] }),
    client.invalidateQueries({ queryKey: ["ws-points", code] }),
    client.invalidateQueries({ queryKey: ["filmthickness"] }),
  ]);
}

export async function refreshWsPoints(client: QueryClient, plant: string) {
  // T114: a change to a Wave Scan list reaches past the list. Counted and
  // retire move the dashboard for every month (D-114-3, D-114-4), History's
  // point tags, the Model cards' counts (D-114-10) and an add or retire the
  // model picker's size.
  const code = plant.toUpperCase();
  await Promise.all([
    client.invalidateQueries({ queryKey: ["ws-points", code] }),
    client.invalidateQueries({ queryKey: ["overview"] }),
    client.invalidateQueries({ queryKey: ["point-profile", code] }),
    client.invalidateQueries({ queryKey: ["history"] }),
    client.invalidateQueries({ queryKey: ["standards", "model-points"] }),
  ]);
}

export const filmStandardsOptions = (plant: string) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["filmthickness", "standards", code],
    queryFn: ({ signal }) => api().filmStandards(code, signal),
    retry: false,
  });
};

export const pointWalkOptions = (
  plant: string,
  domain: "FILMTHICKNESS" | "WAVESCAN",
  model: string,
) => {
  const code = plant.toUpperCase();
  return queryOptions({
    queryKey: ["point-walk", code, domain, model],
    queryFn: ({ signal }) => api().pointWalk(code, domain, model, signal),
    enabled: Boolean(model),
    retry: false,
  });
};

export async function refreshPointWalk(
  client: QueryClient,
  plant: string,
  domain: "FILMTHICKNESS" | "WAVESCAN",
  model: string,
) {
  const code = plant.toUpperCase();
  await Promise.all([
    client.invalidateQueries({ queryKey: ["point-walk", code, domain, model] }),
    refreshPointLabels(client, code),
    refreshWsPoints(client, code),
    refreshActiveMeasurements(client),
    refreshPlantWorkbooks(client, code),
  ]);
}
