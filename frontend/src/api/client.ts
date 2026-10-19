import type { components, paths } from "./types.ts";

type ReadPath =
  | "/api/v1/measurements"
  | "/api/v1/measurements/{measurement_id}"
  | "/api/v1/auth/me"
  | "/api/v1/meta"
  | "/api/v1/dashboard/preview"
  | "/api/v1/batches"
  | "/api/v1/batches/{load_id}"
  | "/api/v1/mappings/proposals"
  | "/api/v1/mappings/proposals/{proposal_id}"
  | "/api/v1/mappings/panel-match"
  | "/api/v1/plants/{plant_code}/workbooks"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}/worksheet"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}/rows"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}/issues"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}/history"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}/vehicles"
  | "/api/v1/plants/{plant_code}/workbooks/{file_hash}/vehicles/{vehicle_id}/points"
  | "/api/v1/plants/{plant_code}/history/facets"
  | "/api/v1/plants/{plant_code}/history/summaries"
  | "/api/v1/plants/{plant_code}/history/vehicles"
  | "/api/v1/plants/{plant_code}/history/vehicles/{vehicle_id}/points"
  | "/api/v1/plants/{plant_code}/wavescan/overview"
  | "/api/v1/plants/{plant_code}/comparison/vehicles"
  | "/api/v1/plants/{plant_code}/comparison/points"
  | "/api/v1/plants/{plant_code}/comparison/vehicle-visuals"
  | "/api/v1/plants/{plant_code}/filmthickness/overview"
  | "/api/v1/plants/{plant_code}/filmthickness/facets"
  | "/api/v1/plants/{plant_code}/filmthickness/summaries"
  | "/api/v1/plants/{plant_code}/filmthickness/vehicles"
  | "/api/v1/plants/{plant_code}/filmthickness/vehicles/{logical_vehicle_id}/points"
  | "/api/v1/plants/{plant_code}/filmthickness/standards"
  | "/api/v1/standards/catalogue"
  | "/api/v1/plants/{plant_code}/model-points"
  | "/api/v1/plants/{plant_code}/analysis/pairing"
  | "/api/v1/plants/{plant_code}/analysis/report"
  | "/api/v1/plants/{plant_code}/analysis/ask"
  | "/api/v1/plants/{plant_code}/analysis/questions"
  | "/api/v1/plants/{plant_code}/color-appearances";
type ResponseFor<P extends ReadPath> =
  paths[P]["get"]["responses"][200]["content"]["application/json"];
export type PreviewQuery = NonNullable<
  paths["/api/v1/dashboard/preview"]["get"]["parameters"]["query"]
>;
export type MeasurementQuery = NonNullable<
  paths["/api/v1/measurements"]["get"]["parameters"]["query"]
>;
export type UploadBody =
  paths["/api/v1/uploads"]["post"]["requestBody"]["content"]["multipart/form-data"];
export type BatchQuery = NonNullable<paths["/api/v1/batches"]["get"]["parameters"]["query"]>;
export type ImgOverviewQuery = paths["/api/v1/img/overview"]["get"]["parameters"]["query"];
export type ImgColorsQuery = paths["/api/v1/img/colors"]["get"]["parameters"]["query"];
export type ProposalQuery = NonNullable<
  paths["/api/v1/mappings/proposals"]["get"]["parameters"]["query"]
>;
export type PanelMatchQuery = NonNullable<
  paths["/api/v1/mappings/panel-match"]["get"]["parameters"]["query"]
>;
export type WorkbookQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/workbooks"]["get"]["parameters"]["query"]
>;
// RO17: the two point domains a label or alias path names.
export type PointDomain =
  paths["/api/v1/plants/{plant_code}/point-labels/{domain}/{model_code}/rename"]["post"]["parameters"]["path"]["domain"];
export type CompletenessImpactQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/ws-points/{model_code}/completeness-impact"]["get"]["parameters"]["query"]
>;
export type WorkbookRowsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/workbooks/{file_hash}/rows"]["get"]["parameters"]["query"]
>;
export type WorkbookVehiclesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/workbooks/{file_hash}/vehicles"]["get"]["parameters"]["query"]
>;
export type WorkbookPointsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/workbooks/{file_hash}/vehicles/{vehicle_id}/points"]["get"]["parameters"]["query"]
>;
export type HistoryFacetsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/history/facets"]["get"]["parameters"]["query"]
>;
export type HistorySummariesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/history/summaries"]["get"]["parameters"]["query"]
>;
export type HistoryVehiclesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/history/vehicles"]["get"]["parameters"]["query"]
>;
export type HistoryPointsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/history/vehicles/{vehicle_id}/points"]["get"]["parameters"]["query"]
>;
export type AnalysisReportQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/analysis/report"]["get"]["parameters"]["query"]
>;
export type AssistantQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/analysis/ask"]["get"]["parameters"]["query"]
>;
export type WavescanOverviewQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/wavescan/overview"]["get"]["parameters"]["query"]
>;
export type FilmOverviewQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/filmthickness/overview"]["get"]["parameters"]["query"]
>;
export type FilmFacetsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/filmthickness/facets"]["get"]["parameters"]["query"]
>;
export type FilmVehiclesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/filmthickness/vehicles"]["get"]["parameters"]["query"]
>;
export type FilmSummariesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/filmthickness/summaries"]["get"]["parameters"]["query"]
>;
export type AcknowledgementBody =
  paths["/api/v1/plants/{plant_code}/workbooks/{file_hash}/acknowledgements"]["post"]["requestBody"]["content"]["application/json"];
export type ProfilePublishBody =
  paths["/api/v1/plants/{plant_code}/template-profiles/publish"]["post"]["requestBody"]["content"]["application/json"];
export type ProposalBody =
  paths["/api/v1/mappings/proposals"]["post"]["requestBody"]["content"]["application/json"];
type ProposalResponse =
  paths["/api/v1/mappings/proposals"]["post"]["responses"][201]["content"]["application/json"];
type ApprovalResponse =
  paths["/api/v1/mappings/proposals/{proposal_id}/approve"]["post"]["responses"][200]["content"]["application/json"];
type UploadResponse =
  paths["/api/v1/uploads"]["post"]["responses"][202]["content"]["application/json"];
type CommitResponse =
  paths["/api/v1/batches/{load_id}/commit"]["post"]["responses"][200]["content"]["application/json"];
type AcknowledgementResponse =
  paths["/api/v1/plants/{plant_code}/workbooks/{file_hash}/acknowledgements"]["post"]["responses"][201]["content"]["application/json"];
type ProfilePublishResponse =
  paths["/api/v1/plants/{plant_code}/template-profiles/publish"]["post"]["responses"][200]["content"]["application/json"];
type ErrorBody = components["schemas"]["ErrorResponse"];
export type ComparisonVehiclesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/comparison/vehicles"]["get"]["parameters"]["query"]
>;
export type ComparisonPointsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/comparison/points"]["get"]["parameters"]["query"]
>;
export type ComparisonVehicleVisualsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/comparison/vehicle-visuals"]["get"]["parameters"]["query"]
>;
export type ComparisonMonthlyPreviewBody =
  paths["/api/v1/plants/{plant_code}/comparison/monthly-preview"]["post"]["requestBody"]["content"]["application/json"];
export type ColorAppearanceSaveBody =
  paths["/api/v1/plants/{plant_code}/color-appearances/{color_name}"]["post"]["requestBody"]["content"]["application/json"];
export type MonthlyProfilesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/monthly-detail/profiles"]["get"]["parameters"]["query"]
>;
export type MonthlyPointsQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/monthly-detail/points"]["get"]["parameters"]["query"]
>;
export type MonthlyPointStatusesQuery = NonNullable<
  paths["/api/v1/plants/{plant_code}/monthly-detail/point-statuses"]["get"]["parameters"]["query"]
>;

function isErrorBody(body: unknown): body is ErrorBody {
  return (
    typeof body === "object" &&
    body !== null &&
    "statusCode" in body &&
    typeof body.statusCode === "number" &&
    "error" in body &&
    typeof body.error === "string" &&
    "message" in body &&
    typeof body.message === "string" &&
    "correlationId" in body &&
    typeof body.correlationId === "string"
  );
}

export class ApiError extends Error {
  readonly status: number;
  readonly body?: ErrorBody;
  constructor(status: number, body?: ErrorBody) {
    super(body?.message ?? `API request returned HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

// RO19: each workbook's answers wait for the preceding re-read. Keep rejected
// promises out of the chain so a bad answer cannot lose the next. Module scope,
// because `api()` builds a fresh client per call, so a per-client queue never
// serialises two real answers.
const answers = new Map<string, Promise<unknown>>();

export function createApiClient(base: string, fetcher: typeof fetch = fetch) {
  const configError = () =>
    new Error(
      "Set VITE_API_BASE_URL to an HTTP(S) origin without a trailing slash, path, query or credentials.",
    );
  let origin: URL;
  try {
    origin = new URL(base);
  } catch {
    throw configError();
  }
  if (!/^https?:$/.test(origin.protocol) || origin.origin !== base) throw configError();

  async function requestNow<T>(
    path: string,
    method: "GET" | "POST" | "PUT",
    query?:
      | MeasurementQuery
      | BatchQuery
      | ProposalQuery
      | PreviewQuery
      | WorkbookQuery
      | WorkbookRowsQuery
      | WorkbookVehiclesQuery
      | WorkbookPointsQuery
      | HistoryFacetsQuery
      | HistorySummariesQuery
      | HistoryVehiclesQuery
      | HistoryPointsQuery
      | WavescanOverviewQuery
      | FilmFacetsQuery
      | FilmVehiclesQuery
      | ComparisonVehiclesQuery
      | ComparisonPointsQuery
      | ComparisonVehicleVisualsQuery
      | CompletenessImpactQuery
      | ImgOverviewQuery
      | ImgColorsQuery
      | MonthlyProfilesQuery
      | MonthlyPointsQuery
      | AnalysisReportQuery
      | AssistantQuery,
    signal?: AbortSignal,
    body?: FormData | string,
  ): Promise<T> {
    const url = new URL(path, origin);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value === undefined || value === null) continue;
      if (Array.isArray(value)) {
        for (const item of value) url.searchParams.append(key, String(item));
      } else {
        url.searchParams.set(key, String(value));
      }
    }
    const response = await fetcher(url, {
      method,
      headers: {
        Accept: "application/json",
        ...(typeof body === "string" ? { "Content-Type": "application/json" } : {}),
      },
      credentials: "omit",
      signal,
      body,
    });
    if (!response.ok) {
      const error: unknown = await response.json().catch(() => undefined);
      throw new ApiError(response.status, isErrorBody(error) ? error : undefined);
    }
    return response.json() as Promise<T>;
  }

  function request<T>(...args: Parameters<typeof requestNow>): Promise<T> {
    const [path, method] = args;
    const match =
      method === "POST" &&
      path.match(
        /^(\/api\/v1\/plants\/[^/]+\/workbooks\/[^/]+)\/(?:panel-confirm|film-point-answer|film-not-a-point|month-answer|film-date-answer|film-model-answer|film-job-answer|film-walk-confirm|hole-approval|ignore-columns|plant-answer)$/,
      );
    if (!match) return requestNow<T>(...args);
    const key = `${origin.origin}${match[1]}`;
    const queued = (answers.get(key) ?? Promise.resolve())
      .catch(() => undefined)
      .then(async () => {
        const result = await requestNow<T>(...args);
        const replayed = (result as { replayed_load_ids?: number[] }).replayed_load_ids ?? [];
        // The answer is saved from here on: waiting for the re-read only orders the
        // next answer, so a failed or slow poll must not report this one as failed.
        const deadline = Date.now() + 60_000;
        while (replayed.length && Date.now() < deadline) {
          const tab = await requestNow<components["schemas"]["WorksheetOut"]>(
            `${key}/worksheet`,
            "GET",
          ).catch(() => null);
          if (
            tab &&
            !tab.sheets.some(
              (sheet) =>
                replayed.includes(sheet.load_id) &&
                (sheet.state === "processing" || sheet.status === "RUNNING"),
            )
          )
            break;
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
        return result;
      });
    answers.set(key, queued);
    void queued
      .finally(() => {
        if (answers.get(key) === queued) answers.delete(key);
      })
      .catch(() => undefined);
    return queued;
  }

  const get = <P extends ReadPath>(
    path: P,
    query?:
      | MeasurementQuery
      | BatchQuery
      | ProposalQuery
      | PreviewQuery
      | WorkbookQuery
      | WorkbookRowsQuery
      | WorkbookVehiclesQuery
      | WorkbookPointsQuery
      | HistoryFacetsQuery
      | HistorySummariesQuery
      | HistoryVehiclesQuery
      | HistoryPointsQuery
      | WavescanOverviewQuery
      | FilmFacetsQuery
      | FilmVehiclesQuery
      | ComparisonVehiclesQuery
      | ComparisonPointsQuery
      | ComparisonVehicleVisualsQuery,
    signal?: AbortSignal,
  ) => request<ResponseFor<P>>(path, "GET", query, signal);

  return {
    pointWalk: (
      plant: string,
      domain: "FILMTHICKNESS" | "WAVESCAN",
      model: string,
      signal?: AbortSignal,
    ) =>
      request<components["schemas"]["PointWalkOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-walk/${domain}/${encodeURIComponent(model)}`,
        "GET",
        undefined,
        signal,
      ),
    setPointWalk: (
      plant: string,
      domain: "FILMTHICKNESS" | "WAVESCAN",
      model: string,
      body: components["schemas"]["PointWalkSetIn"],
    ) =>
      request<components["schemas"]["PointWalkWritten"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-walk/${domain}/${encodeURIComponent(model)}`,
        "PUT",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    dryRunPointWalk: (
      plant: string,
      domain: "FILMTHICKNESS" | "WAVESCAN",
      model: string,
      body: components["schemas"]["PointWalkDryRunIn"],
    ) =>
      request<components["schemas"]["PointWalkDryRunOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-walk/${domain}/${encodeURIComponent(model)}/dry-run`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    monthlyProfiles: (plant: string, query: MonthlyProfilesQuery, signal?: AbortSignal) =>
      request<components["schemas"]["MonthlyProfilesOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/monthly-detail/profiles`,
        "GET",
        query,
        signal,
      ),
    monthlyPoints: (plant: string, query: MonthlyPointsQuery, signal?: AbortSignal) =>
      request<components["schemas"]["MonthlyPointsOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/monthly-detail/points`,
        "GET",
        query,
        signal,
      ),
    monthlyPointStatuses: (plant: string, query: MonthlyPointStatusesQuery, signal?: AbortSignal) =>
      request<components["schemas"]["MonthlyPointStatusesOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/monthly-detail/point-statuses`,
        "GET",
        query,
        signal,
      ),
    pointProfile: (
      plant: string,
      model: string,
      domain: "wavescan" | "film",
      signal?: AbortSignal,
    ) =>
      request<components["schemas"]["PointProfileOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-profiles/${encodeURIComponent(model)}/${domain}`,
        "GET",
        undefined,
        signal,
      ),
    savePointAnchor: (
      plant: string,
      model: string,
      domain: "wavescan" | "film",
      body: components["schemas"]["AnchorSaveIn"],
    ) =>
      request<components["schemas"]["AnchorWritten"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-profiles/${encodeURIComponent(model)}/${domain}/save`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    removePointAnchor: (
      plant: string,
      model: string,
      domain: "wavescan" | "film",
      body: components["schemas"]["AnchorRemoveIn"],
    ) =>
      request<components["schemas"]["AnchorWritten"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-profiles/${encodeURIComponent(model)}/${domain}/remove`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    colorAppearances: (plant: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/color-appearances">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/color-appearances`,
        "GET",
        undefined,
        signal,
      ),
    // Overview IMG: measured months and the family x orientation series of one month.
    imgMonths: (signal?: AbortSignal) =>
      request<
        paths["/api/v1/img/overview/months"]["get"]["responses"][200]["content"]["application/json"]
      >("/api/v1/img/overview/months", "GET", undefined, signal),
    imgOverview: (query: ImgOverviewQuery, signal?: AbortSignal) =>
      request<
        paths["/api/v1/img/overview"]["get"]["responses"][200]["content"]["application/json"]
      >("/api/v1/img/overview", "GET", query, signal),
    imgColors: (query: ImgColorsQuery, signal?: AbortSignal) =>
      request<paths["/api/v1/img/colors"]["get"]["responses"][200]["content"]["application/json"]>(
        "/api/v1/img/colors",
        "GET",
        query,
        signal,
      ),
    landingStatus: (signal?: AbortSignal) =>
      request<
        paths["/api/v1/landing/status"]["get"]["responses"][200]["content"]["application/json"]
      >("/api/v1/landing/status", "GET", undefined, signal),
    pairingReadiness: (plant: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/analysis/pairing">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/analysis/pairing`,
        "GET",
        undefined,
        signal,
      ),
    analysisReport: (plant: string, query: AnalysisReportQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/analysis/report">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/analysis/report`,
        "GET",
        query,
        signal,
      ),
    assistantAnswer: (plant: string, query: AssistantQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/analysis/ask">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/analysis/ask`,
        "GET",
        query,
        signal,
      ),
    assistantQuestions: (plant: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/analysis/questions">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/analysis/questions`,
        "GET",
        undefined,
        signal,
      ),
    saveColorAppearance: (plant: string, colorName: string, body: ColorAppearanceSaveBody) =>
      request<components["schemas"]["ColorAppearanceSaved"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/color-appearances/${encodeURIComponent(colorName)}`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    comparisonVehicles: (plant: string, query: ComparisonVehiclesQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/comparison/vehicles">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/comparison/vehicles`,
        "GET",
        query,
        signal,
      ),
    comparisonPoints: (plant: string, query: ComparisonPointsQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/comparison/points">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/comparison/points`,
        "GET",
        query,
        signal,
      ),
    comparisonMonthlyPreview: (
      plant: string,
      body: ComparisonMonthlyPreviewBody,
      signal?: AbortSignal,
    ) =>
      request<
        paths["/api/v1/plants/{plant_code}/comparison/monthly-preview"]["post"]["responses"][200]["content"]["application/json"]
      >(
        `/api/v1/plants/${encodeURIComponent(plant)}/comparison/monthly-preview`,
        "POST",
        undefined,
        signal,
        JSON.stringify(body),
      ),
    comparisonVehicleVisuals: (
      plant: string,
      query: ComparisonVehicleVisualsQuery,
      signal?: AbortSignal,
    ) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/comparison/vehicle-visuals">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/comparison/vehicle-visuals`,
        "GET",
        query,
        signal,
      ),
    // OpenAPI deliberately has no readiness DTO. Consumers inspect only known strings.
    ready: (signal?: AbortSignal): Promise<unknown> =>
      request<unknown>("/health/ready", "GET", undefined, signal),
    measurements: (query: MeasurementQuery, signal?: AbortSignal) =>
      get("/api/v1/measurements", query, signal),
    measurement: (id: number, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/measurements/{measurement_id}">>(
        `/api/v1/measurements/${id}`,
        "GET",
        undefined,
        signal,
      ),
    correct: (id: number, body: components["schemas"]["CorrectionCreate"]) =>
      request<components["schemas"]["CorrectionResult"]>(
        `/api/v1/measurements/${id}/corrections`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    supersede: (id: number, body: components["schemas"]["SupersedeCreate"]) =>
      request<components["schemas"]["SupersedeResult"]>(
        `/api/v1/batches/${id}/supersede`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    me: (signal?: AbortSignal) => get("/api/v1/auth/me", undefined, signal),
    preview: (query: PreviewQuery = {}, signal?: AbortSignal) =>
      get("/api/v1/dashboard/preview", query, signal),
    meta: (signal?: AbortSignal) => get("/api/v1/meta", undefined, signal),
    batches: (query: BatchQuery = {}, signal?: AbortSignal) =>
      get("/api/v1/batches", query, signal),
    batch: (id: number, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/batches/{load_id}">>(
        `/api/v1/batches/${id}`,
        "GET",
        undefined,
        signal,
      ),
    upload: ({ files, expected_plant }: UploadBody) => {
      const body = new FormData();
      for (const file of files) body.append("files", file);
      body.append("expected_plant", expected_plant);
      return request<UploadResponse>("/api/v1/uploads", "POST", undefined, undefined, body);
    },
    commit: (id: number) => request<CommitResponse>(`/api/v1/batches/${id}/commit`, "POST"),
    proposals: (query: ProposalQuery = {}, signal?: AbortSignal) =>
      get("/api/v1/mappings/proposals", query, signal),
    proposal: (id: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/mappings/proposals/{proposal_id}">>(
        `/api/v1/mappings/proposals/${encodeURIComponent(id)}`,
        "GET",
        undefined,
        signal,
      ),
    // T86: the whole guided panel-match screen in one read. The plant is
    // the batch's own, so this cannot ask for another plant's panel list.
    panelMatch: (query: PanelMatchQuery, signal?: AbortSignal) =>
      get("/api/v1/mappings/panel-match", query, signal),
    propose: (body: ProposalBody) =>
      request<ProposalResponse>(
        "/api/v1/mappings/proposals",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    approve: (id: string) =>
      request<ApprovalResponse>(
        `/api/v1/mappings/proposals/${encodeURIComponent(id)}/approve`,
        "POST",
      ),
    workbooks: (plant: string, query: WorkbookQuery = {}, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/workbooks">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks`,
        "GET",
        query,
        signal,
      ),
    workbook: (plant: string, fileHash: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/workbooks/{file_hash}">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}`,
        "GET",
        undefined,
        signal,
      ),
    worksheet: (plant: string, fileHash: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/workbooks/{file_hash}/worksheet">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/worksheet`,
        "GET",
        undefined,
        signal,
      ),
    ignoreColumns: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["IgnoreColumnsCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/ignore-columns`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    answerPlant: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["PlantAnswerCreate"],
    ) =>
      request<components["schemas"]["PlantAnswerResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/plant-answer`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    approveHoles: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["HoleApprovalCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/hole-approval`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // T94 (D-94-3, D-94-6): which panel a rough panel name is, confirmed in
    // the row of the confirm table. One pair is the row's own Confirm; the
    // whole pre-filled set is the one click.
    confirmPanels: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["PanelConfirmCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/panel-confirm`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    loadReady: (plant: string, fileHash: string) =>
      request<components["schemas"]["WorkbookLoadResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/load-ready`,
        "POST",
      ),
    loadRemaining: (plant: string, fileHash: string) =>
      request<components["schemas"]["WorkbookLoadResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/load-remaining`,
        "POST",
      ),
    workbookRows: (
      plant: string,
      fileHash: string,
      query: WorkbookRowsQuery = {},
      signal?: AbortSignal,
    ) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/workbooks/{file_hash}/rows">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/rows`,
        "GET",
        query,
        signal,
      ),
    workbookIssues: (plant: string, fileHash: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/workbooks/{file_hash}/issues">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/issues`,
        "GET",
        undefined,
        signal,
      ),
    workbookHistory: (plant: string, fileHash: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/workbooks/{file_hash}/history">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/history`,
        "GET",
        undefined,
        signal,
      ),
    workbookVehicles: (
      plant: string,
      fileHash: string,
      query: WorkbookVehiclesQuery,
      signal?: AbortSignal,
    ) =>
      request<components["schemas"]["VehicleSetPage"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/vehicles`,
        "GET",
        query,
        signal,
      ),
    workbookVehiclePoints: (
      plant: string,
      fileHash: string,
      vehicleId: string,
      query: WorkbookPointsQuery = {},
      signal?: AbortSignal,
    ) =>
      request<components["schemas"]["VehiclePointPage"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/vehicles/${encodeURIComponent(vehicleId)}/points`,
        "GET",
        query,
        signal,
      ),
    historyFacets: (plant: string, query: HistoryFacetsQuery = {}, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/history/facets">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/history/facets`,
        "GET",
        query,
        signal,
      ),
    historySummaries: (plant: string, query: HistorySummariesQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/history/summaries">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/history/summaries`,
        "GET",
        query,
        signal,
      ),
    historyVehicles: (plant: string, query: HistoryVehiclesQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/history/vehicles">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/history/vehicles`,
        "GET",
        query,
        signal,
      ),
    historyVehiclePoints: (
      plant: string,
      vehicleId: string,
      query: HistoryPointsQuery = {},
      signal?: AbortSignal,
    ) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/history/vehicles/{vehicle_id}/points">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/history/vehicles/${encodeURIComponent(vehicleId)}/points`,
        "GET",
        query,
        signal,
      ),
    wavescanOverview: (plant: string, query: WavescanOverviewQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/wavescan/overview">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/wavescan/overview`,
        "GET",
        query,
        signal,
      ),
    // T99 / T100: the three sheet answers and the points setting. Typed off
    // the generated schemas rather than ResponseFor, so the broken
    // comparison entries in ReadPath above are not in the way.
    answerFilmModel: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["FilmModelAnswerCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/film-model-answer`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    answerFilmJob: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["FilmJobAnswerCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/film-job-answer`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    confirmFilmWalk: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["FilmWalkConfirmCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/film-walk-confirm`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    filmModels: (plant: string, signal?: AbortSignal) =>
      request<components["schemas"]["FilmModelsOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points`,
        "GET",
        undefined,
        signal,
      ),
    filmPointSetting: (plant: string, model: string, signal?: AbortSignal) =>
      request<components["schemas"]["FilmPointSettingOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}`,
        "GET",
        undefined,
        signal,
      ),
    changeFilmPointSetting: (
      plant: string,
      model: string,
      body: components["schemas"]["FilmPointSettingCreate"],
    ) =>
      request<components["schemas"]["FilmPointSettingResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // T109 (D-109-5 / D-109-4 / D-109-6): Point Check's two writes and the
    // review row's answer. All three are POSTs: nothing here is an UPDATE of
    // a setting row, and nothing is a delete.
    addFilmPoint: (
      plant: string,
      model: string,
      body: components["schemas"]["FilmPointAddCreate"],
    ) =>
      request<components["schemas"]["FilmPointChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}/add`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    retireFilmPoint: (
      plant: string,
      model: string,
      body: components["schemas"]["FilmPointRetireCreate"],
    ) =>
      request<components["schemas"]["FilmPointChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}/retire`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    answerFilmPoint: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["FilmPointAliasCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/film-point-answer`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // RO18 (B5): "Not a point of this list: keep it, never load it".
    answerFilmNotAPoint: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["FilmNotAPointCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/film-not-a-point`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // RO18 (B4): the month an undated sheet's cars were measured in (either domain).
    answerMonth: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["MonthAnswerCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/month-answer`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // RO18 (B3): which date of a Film sheet is right, the sheet's or the file name's.
    answerFilmDate: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["FilmDateAnswerCreate"],
    ) =>
      request<components["schemas"]["DecisionResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/film-date-answer`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // T114 (D-114-1..7): Point Check's Wave Scan section. Two reads and three
    // POSTs; nothing is an UPDATE of a setting row and nothing is a delete.
    wsPointModels: (plant: string, signal?: AbortSignal) =>
      request<components["schemas"]["WsPointModelsOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points`,
        "GET",
        undefined,
        signal,
      ),
    wsPointList: (plant: string, model: string, signal?: AbortSignal) =>
      request<components["schemas"]["WsPointListOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points/${encodeURIComponent(model)}`,
        "GET",
        undefined,
        signal,
      ),
    changeWsPointSetting: (
      plant: string,
      model: string,
      body: components["schemas"]["WsPointSettingCreate"],
    ) =>
      request<components["schemas"]["WsPointSettingResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points/${encodeURIComponent(model)}`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    addWsPoint: (plant: string, model: string, body: components["schemas"]["WsPointAddCreate"]) =>
      request<components["schemas"]["WsPointChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points/${encodeURIComponent(model)}/add`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    retireWsPoint: (
      plant: string,
      model: string,
      body: components["schemas"]["WsPointRetireCreate"],
    ) =>
      request<components["schemas"]["WsPointChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points/${encodeURIComponent(model)}/retire`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    // RO17 (D-RO17-6..13): restore, rename, tail labels, aliases. All POSTs
    // append or set a retire column; nothing is a delete.
    restoreWsPoint: (
      plant: string,
      model: string,
      body: components["schemas"]["WsPointRestoreCreate"],
    ) =>
      request<components["schemas"]["WsPointChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points/${encodeURIComponent(model)}/restore`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    wsCompletenessImpact: (plant: string, model: string, zoneCode: string, signal?: AbortSignal) =>
      request<components["schemas"]["WsCompletenessImpactOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/ws-points/${encodeURIComponent(model)}/completeness-impact`,
        "GET",
        { zone_code: zoneCode },
        signal,
      ),
    restoreFilmPoint: (
      plant: string,
      model: string,
      body: components["schemas"]["FilmPointRestoreCreate"],
    ) =>
      request<components["schemas"]["FilmPointChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}/restore`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    addFilmTailLabel: (
      plant: string,
      model: string,
      body: components["schemas"]["FilmTailLabelCreate"],
    ) =>
      request<components["schemas"]["FilmTailLabelResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}/tail-labels`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    retireFilmTailLabel: (
      plant: string,
      model: string,
      body: components["schemas"]["FilmTailLabelRetireCreate"],
    ) =>
      request<components["schemas"]["FilmTailLabelResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/film-points/${encodeURIComponent(model)}/tail-labels/retire`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    pointLabels: (plant: string, signal?: AbortSignal) =>
      request<components["schemas"]["PointLabelsOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-labels`,
        "GET",
        undefined,
        signal,
      ),
    renamePoint: (
      plant: string,
      domain: PointDomain,
      model: string,
      body: components["schemas"]["PointLabelRenameCreate"],
    ) =>
      request<components["schemas"]["PointLabelChangeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-labels/${domain}/${encodeURIComponent(model)}/rename`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    pointAliases: (plant: string, domain: PointDomain, model: string, signal?: AbortSignal) =>
      request<components["schemas"]["PointAliasesOut"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-aliases/${domain}/${encodeURIComponent(model)}`,
        "GET",
        undefined,
        signal,
      ),
    retirePointAlias: (
      plant: string,
      domain: PointDomain,
      model: string,
      body: components["schemas"]["PointAliasRetireCreate"],
    ) =>
      request<components["schemas"]["PointAliasRetireResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/point-aliases/${domain}/${encodeURIComponent(model)}/retire`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    filmStandards: (plant: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/filmthickness/standards">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/filmthickness/standards`,
        "GET",
        undefined,
        signal,
      ),
    publishFilmStandard: (body: components["schemas"]["FilmStandardPublishIn"]) =>
      request<components["schemas"]["FilmStandardPublishOut"]>(
        "/api/v1/filmthickness/standards",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    filmOverview: (plant: string, query: FilmOverviewQuery = {}, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/filmthickness/overview">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/filmthickness/overview`,
        "GET",
        query,
        signal,
      ),
    filmFacets: (plant: string, query: FilmFacetsQuery = {}, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/filmthickness/facets">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/filmthickness/facets`,
        "GET",
        query,
        signal,
      ),
    filmSummaries: (plant: string, query: FilmSummariesQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/filmthickness/summaries">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/filmthickness/summaries`,
        "GET",
        query,
        signal,
      ),
    filmVehicles: (plant: string, query: FilmVehiclesQuery, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/filmthickness/vehicles">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/filmthickness/vehicles`,
        "GET",
        query,
        signal,
      ),
    filmVehiclePoints: (plant: string, vehicleId: string, signal?: AbortSignal) =>
      request<
        ResponseFor<"/api/v1/plants/{plant_code}/filmthickness/vehicles/{logical_vehicle_id}/points">
      >(
        `/api/v1/plants/${encodeURIComponent(plant)}/filmthickness/vehicles/${encodeURIComponent(vehicleId)}/points`,
        "GET",
        undefined,
        signal,
      ),
    overrideWorkbook: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["OverrideCreate"],
    ) =>
      request<components["schemas"]["OverrideResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/overrides`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    abandon: (id: number, body: components["schemas"]["AbandonCreate"]) =>
      request<components["schemas"]["AbandonResult"]>(
        `/api/v1/batches/${id}/abandon`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    purgeWorkbook: (
      plant: string,
      fileHash: string,
      body: components["schemas"]["WorkbookPurgeCreate"],
    ) =>
      request<components["schemas"]["WorkbookPurgeResult"]>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/purge`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    acknowledge: (plant: string, fileHash: string, body: AcknowledgementBody) =>
      request<AcknowledgementResponse>(
        `/api/v1/plants/${encodeURIComponent(plant)}/workbooks/${encodeURIComponent(fileHash)}/acknowledgements`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    publishTemplateProfile: (plant: string, body: ProfilePublishBody) =>
      request<ProfilePublishResponse>(
        `/api/v1/plants/${encodeURIComponent(plant)}/template-profiles/publish`,
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    catalogue: (signal?: AbortSignal) => get("/api/v1/standards/catalogue", undefined, signal),
    modelPoints: (plant: string, signal?: AbortSignal) =>
      request<ResponseFor<"/api/v1/plants/{plant_code}/model-points">>(
        `/api/v1/plants/${encodeURIComponent(plant)}/model-points`,
        "GET",
        undefined,
        signal,
      ),
    mintColour: (body: components["schemas"]["ColorMintIn"]) =>
      request<components["schemas"]["ColourMintOut"]>(
        "/api/v1/standards/colours",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    setPlantColour: (body: components["schemas"]["PlantColorPatchIn"]) =>
      request<components["schemas"]["PlantColorPatchOut"]>(
        "/api/v1/standards/plant-colours",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    attachPlantModels: (body: components["schemas"]["PlantModelAttachIn"]) =>
      request<components["schemas"]["PlantModelAttachOut"]>(
        "/api/v1/standards/plant-models",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    setPlantModelOffered: (body: components["schemas"]["PlantModelOfferedIn"]) =>
      request<components["schemas"]["PlantModelOfferedOut"]>(
        "/api/v1/standards/plant-models/offered",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
    publishStandard: (body: components["schemas"]["StandardPublishIn"]) =>
      request<components["schemas"]["StandardPublishOut"]>(
        "/api/v1/standards",
        "POST",
        undefined,
        undefined,
        JSON.stringify(body),
      ),
  };
}
