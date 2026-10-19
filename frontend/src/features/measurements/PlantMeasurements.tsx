import type { ReactNode } from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowLeft, ChevronDown } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  filmOverviewOptions,
  metaOptions,
  meOptions,
  wavescanOverviewOptions,
  monthlyProfilesOptions,
} from "@/api/queries";
import { isAdmin, mayCorrect, mayEditFilmPoints, mayIngest } from "@/api/roles";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { MeasurementHistory } from "./MeasurementHistory";
import { DataChildrenNav } from "./DataChildrenNav";
import { StandardChildrenNav } from "./StandardChildrenNav";
import { ModelStudioNav, type ModelDetailView } from "./model-studio/ModelStudioNav";
import { PlantFiles } from "./PlantFiles";
import { FilterPanel, type ActiveMode, type PaintFunction } from "@/components/ct/FilterPanel";
import { SettingsPanel, type SettingId } from "@/components/ct/SettingsPanel";
import { PlantStandard } from "./PlantStandard";
import { CarsFact, CompactFeedStatus, FeedFact, UploadFact } from "./PlantStatusBays";
import { PlantOverview } from "./PlantOverview";
import { PlantComparison } from "./PlantComparison";
import { emptyBench, type Bench } from "./comparison-bench";
import { FilmStandards } from "@/features/filmthickness/FilmStandards";
import { FilmOverview } from "@/features/filmthickness/FilmOverview";
import { calendarYearMonth, defaultDataMonth, toggleFilterValue } from "./overview-display";
import { AnalysisWorkspace } from "@/features/analysis/AnalysisWorkspace";
import { WorkspaceLayout } from "./WorkspaceLayout";
import { useCompactWorkspace } from "./use-compact-workspace";

const SETTING_LABEL: Record<SettingId, string> = {
  data: "Data",
  standard: "Standard",
  model: "Model Detail",
};

const ModelStudio = lazy(() =>
  import("./model-studio/ModelStudio").then((m) => ({ default: m.ModelStudio })),
);
const MonthlyDetail = lazy(() =>
  import("./monthly-detail/MonthlyDetail").then((m) => ({ default: m.MonthlyDetail })),
);

const isSetting = (a: ActiveMode): a is SettingId =>
  a === "data" || a === "standard" || a === "model";

function Bay({
  label,
  children,
  last = false,
}: {
  num: number;
  label: string;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <div
      aria-label={label}
      className={`group relative min-w-0 flex-1 px-5 py-4 transition-colors duration-200 hover:bg-[var(--surface-2)] ${last ? "" : "border-r border-border"}`}
    >
      <div className="relative z-10">
        <p className="mb-1 text-xs text-muted-foreground">{label}</p>
        {children}
      </div>
    </div>
  );
}

export function PlantMeasurements({ code }: { code: string }) {
  const compact = useCompactWorkspace();
  const [statusExpanded, setStatusExpanded] = useState(false);
  const [pointerNavigation, setPointerNavigation] = useState(false);
  const label = code.toUpperCase();
  const search = useSearch({ from: "/plant/$code" });
  const navigate = useNavigate();
  const metadata = useQuery(metaOptions);
  const identity = useQuery(meOptions);
  const plant = metadata.data?.plants.find((p) => p.plant_code === label);
  const month = new Date().toLocaleString("en-US", { month: "long" });
  const calendarMonth = calendarYearMonth();
  const [active, setActive] = useState<ActiveMode>(() =>
    search.dataView || search.file
      ? "data"
      : search.modelView || search.standardView === "model" || search.standardView === "points"
        ? "model"
        : search.standardView
          ? "standard"
          : search.compare
            ? "comparison"
            : "overview",
  );
  const paintFunction: PaintFunction = search.paint === "film" ? "film" : "wavescan";
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const modelView: ModelDetailView =
    search.modelView ??
    (search.standardView === "model"
      ? "model"
      : search.standardView === "points"
        ? "point-check"
        : "colours");
  const studioMode = modelView === "inspection" ? "points" : "colours";
  const [studioModeLocked, setStudioModeLocked] = useState(false);
  const studioLeaveGuard = useRef<(() => boolean) | null>(null);
  const registerStudioLeaveGuard = useCallback((guard: (() => boolean) | null) => {
    studioLeaveGuard.current = guard;
  }, []);
  const mayLeaveStudio = (next: ActiveMode) =>
    active !== "model" || next === "model" || studioLeaveGuard.current?.() !== false;
  const [selectedColors, setSelectedColors] = useState<string[]>([]);
  const [dataMonth, setDataMonth] = useState(calendarMonth);
  const [detailMonths, setDetailMonths] = useState<{ wavescan?: string; film?: string }>({});
  const monthly = useQuery({
    ...monthlyProfilesOptions(label, { domain: paintFunction, month: detailMonths[paintFunction] }),
    enabled: active === "detail",
  });
  const monthlyModels = [...new Set(monthly.data?.items.map((p) => p.model_code) ?? [])];
  const monthlyColors = [...new Set(monthly.data?.items.map((p) => p.color_name) ?? [])].map(
    (color_name) => ({ color_name }),
  );
  const [comparisonBench, setComparisonBench] = useState<{
    plant: string;
    benches: Partial<Record<Bench["domain"], Bench>>;
  }>({
    plant: label,
    benches: {},
  });
  const comparisonDomain = paintFunction === "film" ? "FILMTHICKNESS" : "WAVESCAN";
  const bench =
    comparisonBench.plant === label
      ? (comparisonBench.benches[comparisonDomain] ?? emptyBench(comparisonDomain))
      : emptyBench(comparisonDomain);
  const setBench = (next: Bench) =>
    setComparisonBench((previous) => ({
      plant: label,
      benches: { ...(previous.plant === label ? previous.benches : {}), [next.domain]: next },
    }));
  useEffect(() => {
    if (comparisonBench.plant !== label) setComparisonBench({ plant: label, benches: {} });
  }, [comparisonBench.plant, label]);
  const canManage = identity.isSuccess && mayIngest(identity.data.principal);
  const showFiles = canManage && search.dataView !== "history";
  const standardView = search.standardView === "film" ? "film" : "family";
  useEffect(() => {
    if (search.dataView || search.file) setActive("data");
    else if (
      search.modelView ||
      search.standardView === "model" ||
      search.standardView === "points"
    )
      setActive("model");
    else if (search.standardView) setActive("standard");
    else setActive("overview");
  }, [search.modelView, search.standardView, search.dataView, search.file]);
  // A shared link opens Comparison; the bench then drops the param, which must not close it.
  useEffect(() => {
    if (search.compare) setActive("comparison");
  }, [search.compare]);
  const overviewQuery = {
    month: dataMonth,
    ...(selectedModels.length ? { model: selectedModels } : {}),
    ...(selectedColors.length ? { color: selectedColors } : {}),
  };
  const overview = useQuery({
    ...wavescanOverviewOptions(label, overviewQuery),
    enabled: active === "overview" && paintFunction === "wavescan",
    placeholderData: keepPreviousData,
  });
  const filmOn = active === "overview" && paintFunction === "film";
  const filmMonth = search.filmMonth;
  const filmColors = search.filmColors?.length
    ? search.filmColors
    : search.filmColor
      ? [search.filmColor]
      : [];
  const filmOverview = useQuery({
    ...filmOverviewOptions(label, {
      ...(filmMonth ? { month: filmMonth } : {}),
      ...(search.filmModel ? { models: [search.filmModel] } : {}),
      ...(filmColors.length ? { colors: filmColors } : {}),
    }),
    enabled: filmOn,
  });
  const setFilmSearch = (next: typeof search, replace = false) =>
    void navigate({ to: "/plant/$code", params: { code }, search: next, replace });
  // One switch for the left panel and the Comparison deck.
  const setPaintFunction = (next: PaintFunction) =>
    setFilmSearch(
      next === "film"
        ? { ...search, paint: "film" }
        : {
            ...search,
            paint: undefined,
            filmMonth: undefined,
            filmModel: undefined,
            filmColor: undefined,
            filmColors: undefined,
            filmVehicle: undefined,
          },
    );

  useEffect(() => {
    if (filmOn && !search.filmMonth && filmOverview.data?.month) {
      void navigate({
        to: "/plant/$code",
        params: { code },
        search: { ...search, filmMonth: filmOverview.data.month },
        replace: true,
      });
    }
  }, [filmOn, search, filmOverview.data, navigate, code]);
  const setDataView = (dataView: "upload" | "history", file?: string, sheet?: number) =>
    void navigate({
      to: "/plant/$code",
      params: { code },
      search: {
        ...search,
        standardView: undefined,
        modelView: undefined,
        dataView,
        file,
        sheet,
        paint: undefined,
        filmMonth: undefined,
        filmModel: undefined,
        filmColor: undefined,
        filmColors: undefined,
        filmVehicle: undefined,
      },
    });
  const setStandardView = (next: "family" | "film") =>
    void navigate({ to: "/plant/$code", params: { code }, search: { standardView: next } });
  const selectModelView = (next: ModelDetailView) => {
    if (studioModeLocked || (next !== modelView && studioLeaveGuard.current?.() === false)) return;
    setActive("model");
    void navigate({ to: "/plant/$code", params: { code }, search: { modelView: next } });
  };
  const selectSetting = (id: SettingId) => {
    if (!mayLeaveStudio(id)) return;
    setActive(id);
    if (id === "standard") {
      setStandardView(standardView);
    } else if (id === "data") {
      setDataView(showFiles ? "upload" : "history", search.file, search.sheet);
    } else if (id === "model") {
      selectModelView(modelView);
    }
  };
  const monthOnList = overview.data?.available_months.includes(dataMonth) ?? false;
  const awaitingMonth = Boolean(
    overview.data &&
    overview.data.available_months.length > 0 &&
    !overview.data.available_months.includes(dataMonth),
  );

  useEffect(() => {
    const months = overview.data?.available_months;
    if (!months) return;
    const next = defaultDataMonth(calendarMonth, months);
    if (next !== dataMonth && !months.includes(dataMonth)) setDataMonth(next);
  }, [overview.data?.available_months, calendarMonth, dataMonth]);

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <a className="skip-workspace" href="#workspace-results">
        Skip to workspace
      </a>
      <header aria-label="Plant dashboard" className="p-3 lg:p-4">
        <div className="plant-status-shell panel flex flex-col overflow-hidden xl:flex-row">
          <div
            className="plant-status-identity flex items-center gap-4 border-r border-border px-5 py-4"
            style={{
              background: `linear-gradient(135deg, var(--primary-soft) 0%, var(--panel-raised) 70%)`,
              boxShadow: "inset 0 2px 0 var(--color-primary)",
            }}
          >
            <Link
              to="/"
              className="flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-border text-muted-foreground transition-colors hover:text-foreground"
              aria-label="Back to tracking home"
              onPointerDown={() => setPointerNavigation(true)}
              onKeyDown={() => setPointerNavigation(false)}
              viewTransition={
                pointerNavigation && !matchMedia("(prefers-reduced-motion: reduce)").matches
                  ? { types: ["plant-return"] }
                  : false
              }
            >
              <ArrowLeft className="size-4" />
            </Link>
            <div>
              <p className="text-xs leading-tight text-muted-foreground">Paint Appearance</p>
              <h1 className="mt-0.5 text-2xl font-bold leading-tight tracking-tight">{label}</h1>
            </div>
          </div>

          <button
            type="button"
            className="plant-status-toggle"
            aria-expanded={statusExpanded}
            aria-controls="plant-status-facts"
            onClick={() => setStatusExpanded((value) => !value)}
          >
            <span className="text-left">
              Plant status
              <CompactFeedStatus code={label} />
            </span>{" "}
            <ChevronDown
              size={16}
              style={{ transform: statusExpanded ? "rotate(180deg)" : undefined }}
            />
          </button>
          <div
            id="plant-status-facts"
            className="plant-status-facts"
            data-collapsed={compact && !statusExpanded}
            inert={compact && !statusExpanded}
          >
            <Bay num={1} label="Domain / Process">
              <p className="truncate text-sm font-bold">PAINT APPEARANCE</p>
              {metadata.isError ? (
                <ApiErrorState error={metadata.error} retry={() => void metadata.refetch()} />
              ) : (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {metadata.isPending
                    ? "Loading plant name..."
                    : (plant?.plant_name ?? "Unknown plant: code not found in metadata.")}
                </p>
              )}
            </Bay>

            <Bay num={2} label="Current Month">
              <p className="text-sm font-bold">{month}</p>
              <p className="num mt-0.5 text-[11px] text-muted-foreground">
                {new Date().getFullYear()}
              </p>
            </Bay>

            {/* Live plant facts, from the same read as the landing cards. */}
            <Bay num={3} label="Data Feed">
              <FeedFact code={label} />
            </Bay>
            <Bay num={4} label="Last Upload">
              <UploadFact code={label} />
            </Bay>
            <Bay num={5} label="Cars on File" last>
              <CarsFact code={label} />
            </Bay>
          </div>
        </div>
      </header>
      <main className="flex-1 px-3 pb-3 lg:px-4 lg:pb-4">
        <WorkspaceLayout
          code={label}
          active={active}
          navigationKey={`${active}:${active === "model" ? modelView : active === "standard" ? standardView : active === "data" ? showFiles : ""}`}
          domain={
            active === "overview" || active === "detail" || active === "comparison"
              ? paintFunction === "film"
                ? "Film Thickness"
                : "WaveScan"
              : undefined
          }
          navigation={
            <div className="flex flex-col gap-3 self-start">
              <FilterPanel
                active={active}
                onActiveChange={(next) => {
                  if (mayLeaveStudio(next)) setActive(next);
                }}
                overview={{
                  paintFunction,
                  onPaintFunction: setPaintFunction,
                  modelOptions:
                    active === "detail"
                      ? monthlyModels
                      : paintFunction === "film"
                        ? (filmOverview.data?.model_options ?? [])
                        : (overview.data?.model_options ?? []),
                  selectedModels:
                    paintFunction === "film"
                      ? search.filmModel
                        ? [search.filmModel]
                        : []
                      : selectedModels,
                  onToggleModel: (code) =>
                    paintFunction === "film"
                      ? setFilmSearch({
                          ...search,
                          filmModel: search.filmModel === code ? undefined : code,
                          filmColor: undefined,
                          filmColors: undefined,
                          filmVehicle: undefined,
                        })
                      : setSelectedModels(
                          toggleFilterValue(
                            selectedModels,
                            active === "detail"
                              ? monthlyModels
                              : (overview.data?.model_options ?? []),
                            code,
                          ),
                        ),
                  colorOptions:
                    active === "detail"
                      ? monthlyColors
                      : paintFunction === "film"
                        ? (filmOverview.data?.color_options ?? [])
                        : (overview.data?.color_options ?? []),
                  selectedColors: paintFunction === "film" ? filmColors : selectedColors,
                  onToggleColor: (name) =>
                    paintFunction === "film"
                      ? setFilmSearch({
                          ...search,
                          filmColor: undefined,
                          filmColors: (() => {
                            const next = toggleFilterValue(
                              filmColors,
                              (active === "detail"
                                ? monthlyColors
                                : (filmOverview.data?.color_options ?? [])
                              ).map((colour) => colour.color_name),
                              name,
                            );
                            return next.length ? next : undefined;
                          })(),
                          filmVehicle: undefined,
                        })
                      : setSelectedColors(
                          toggleFilterValue(
                            selectedColors,
                            (active === "detail"
                              ? monthlyColors
                              : (overview.data?.color_options ?? [])
                            ).map((color) => color.color_name),
                            name,
                          ),
                        ),
                  monthOptions:
                    active === "detail"
                      ? (monthly.data?.available_months ?? [])
                      : paintFunction === "film"
                        ? (filmOverview.data?.available_months ?? [])
                        : (overview.data?.available_months ?? []),
                  selectedMonth:
                    active === "detail"
                      ? (monthly.data?.month ?? null)
                      : paintFunction === "film"
                        ? (filmMonth ?? null)
                        : monthOnList
                          ? dataMonth
                          : null,
                  calendarMonth,
                  onSelectMonth: (next) =>
                    active === "detail"
                      ? setDetailMonths((previous) => ({ ...previous, [paintFunction]: next }))
                      : paintFunction === "film"
                        ? setFilmSearch({
                            ...search,
                            filmMonth: next,
                            filmModel: undefined,
                            filmColor: undefined,
                            filmColors: undefined,
                            filmVehicle: undefined,
                          })
                        : setDataMonth(next),
                  onClear: () => {
                    setFilmSearch({
                      ...search,
                      paint: undefined,
                      filmMonth: undefined,
                      filmModel: undefined,
                      filmColor: undefined,
                      filmColors: undefined,
                      filmVehicle: undefined,
                    });
                    setSelectedModels([]);
                    setSelectedColors([]);
                    setDataMonth(calendarMonth);
                    setDetailMonths({});
                  },
                }}
              />
              <SettingsPanel
                modelChildren={
                  <ModelStudioNav
                    mode={modelView}
                    disabled={studioModeLocked}
                    canEditPoints={identity.isSuccess && mayEditFilmPoints(identity.data.principal)}
                    onSelect={selectModelView}
                  />
                }
                active={isSetting(active) ? active : null}
                onSelect={selectSetting}
                dataChildren={
                  identity.isSuccess && (
                    <DataChildrenNav
                      canManage={canManage}
                      view={showFiles ? "upload" : "history"}
                      onSelect={setDataView}
                    />
                  )
                }
                standardChildren={
                  <StandardChildrenNav
                    canEditFilm={identity.isSuccess && isAdmin(identity.data.principal)}
                    view={standardView}
                    onSelect={(next) => {
                      setActive("standard");
                      setStandardView(next);
                    }}
                  />
                }
              />
            </div>
          }
        >
          <div
            key={
              active === "data"
                ? `data-${label}`
                : active === "standard"
                  ? `standard-${label}-${standardView}`
                  : active === "overview"
                    ? `overview-${label}-${paintFunction}${paintFunction === "film" ? "" : `-${dataMonth}`}`
                    : active === "comparison"
                      ? `comparison-${label}`
                      : active
            }
            className="min-w-0"
          >
            {active === "data" && identity.isError ? (
              <div className="panel">
                <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />
              </div>
            ) : active === "data" && identity.isPending ? (
              <div className="panel">
                <LoadingState>Loading API identity...</LoadingState>
              </div>
            ) : active === "data" ? (
              <>
                {showFiles ? (
                  <PlantFiles
                    key={label}
                    code={label}
                    inactive={plant?.is_active === false}
                    file={search.file}
                    sheet={search.sheet}
                    domain={search.dataDomain ?? "both"}
                    onDomainChange={(dataDomain) =>
                      void navigate({
                        to: "/plant/$code",
                        params: { code },
                        search: { ...search, dataDomain },
                      })
                    }
                    onOpen={(file, sheet) => setDataView("upload", file, sheet)}
                  />
                ) : (
                  <MeasurementHistory
                    key={label}
                    code={label}
                    canCorrect={!identity.isError && mayCorrect(identity.data?.principal)}
                    search={search}
                    onSearch={(next, replace) =>
                      void navigate({
                        to: "/plant/$code",
                        params: { code },
                        search: {
                          ...next,
                          dataDomain: next.dataDomain ?? search.dataDomain,
                          dataView: "history",
                        },
                        replace,
                      })
                    }
                  />
                )}
              </>
            ) : active === "standard" ? (
              standardView === "film" ? (
                <FilmStandards code={label} />
              ) : (
                <PlantStandard code={label} view={standardView} />
              )
            ) : active === "overview" ? (
              paintFunction === "film" ? (
                <FilmOverview
                  data={filmOverview.data}
                  isLoading={filmOverview.isPending || filmOverview.isFetching}
                  error={filmOverview.error}
                  retry={() => void filmOverview.refetch()}
                />
              ) : (
                <PlantOverview
                  month={dataMonth}
                  data={overview.data}
                  isPending={overview.isPending || awaitingMonth}
                  isError={overview.isError}
                  error={overview.error}
                  onRetry={() => void overview.refetch()}
                  selectedModels={selectedModels}
                />
              )
            ) : active === "comparison" ? (
              <PlantComparison
                key={`${label}:${paintFunction}`}
                code={label}
                bench={bench}
                onBenchChange={setBench}
                shared={search.compare}
                domain={paintFunction === "film" ? "FILMTHICKNESS" : "WAVESCAN"}
                onDomainChange={(d) =>
                  setPaintFunction(d === "FILMTHICKNESS" ? "film" : "wavescan")
                }
              />
            ) : active === "model" ? (
              modelView === "model" || modelView === "point-check" ? (
                <PlantStandard
                  key={`${label}-${modelView}`}
                  code={label}
                  view={modelView === "model" ? "model" : "points"}
                />
              ) : (
                <Suspense fallback={<LoadingState>Loading Model Detail…</LoadingState>}>
                  <ModelStudio
                    key={label}
                    code={label}
                    mode={studioMode}
                    onModeLockChange={setStudioModeLocked}
                    registerLeaveGuard={registerStudioLeaveGuard}
                  />
                </Suspense>
              )
            ) : active === "detail" ? (
              <Suspense fallback={<LoadingState>Loading Monthly Detail…</LoadingState>}>
                <MonthlyDetail
                  key={`${label}:${paintFunction}`}
                  code={label}
                  data={monthly.data}
                  isPending={monthly.isPending || monthly.isFetching}
                  error={monthly.error}
                  retry={() => void monthly.refetch()}
                  models={
                    paintFunction === "film"
                      ? search.filmModel
                        ? [search.filmModel]
                        : []
                      : selectedModels
                  }
                  colors={paintFunction === "film" ? filmColors : selectedColors}
                />
              </Suspense>
            ) : active === "analysis" ? (
              <AnalysisWorkspace code={label} />
            ) : (
              <SettingsPlaceholder label={SETTING_LABEL[active]} />
            )}
          </div>
        </WorkspaceLayout>
      </main>
    </div>
  );
}

function AnalysisPlaceholder() {
  return (
    <section
      className="panel animate-rise flex min-h-[420px] flex-col items-center justify-center gap-3 px-5 py-4"
      style={{ animationDelay: "80ms" }}
    >
      <p className="eyebrow">Analysis & Report</p>
      <p className="max-w-xs text-center text-xs text-muted-foreground">
        Analysis and reporting workspace - content ships later.
      </p>
    </section>
  );
}

function SettingsPlaceholder({ label }: { label: string }) {
  return (
    <section
      className="panel animate-rise flex min-h-[420px] flex-col items-center justify-center gap-3 px-5 py-4"
      style={{ animationDelay: "80ms" }}
    >
      <p className="eyebrow">{label}</p>
      <p className="max-w-xs text-center text-xs text-muted-foreground">
        Configuration lens - content ships later.
      </p>
    </section>
  );
}
