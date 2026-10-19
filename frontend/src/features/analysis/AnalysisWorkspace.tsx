/**
 * AR03: the Analysis & Report workspace for one plant month (container).
 *
 * Reads the report and the two Monthly Overview responses, holds the page
 * choices, and builds the slides: the overview charts are drawn off-page in
 * the light theme and captured, so the deck shows the dashboard's own
 * boxplots. The page itself is `AnalysisReportView`.
 */

import { Component, useRef, useState, type ReactNode, type RefObject } from "react";
import { useQuery } from "@tanstack/react-query";
import { analysisReportOptions, filmOverviewOptions, wavescanOverviewOptions } from "@/api/queries";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { PlantOverview } from "@/features/measurements/PlantOverview";
import { PointLabelsProvider } from "@/features/measurements/point-labels";
import {
  groupFilmBoxes,
  type FilmOverviewData,
} from "@/features/filmthickness/film-overview-display";
import { FilmOverviewChart } from "@/features/filmthickness/FilmOverviewChart";
import "@/features/filmthickness/film-overview.css";
import { AnalysisReportView, type Sections, type WavescanData } from "./AnalysisReportView";
import { AssistantPanel } from "./AssistantPanel";
import { liveNames, type Ask } from "./assistant-intents";
import { PairingReadiness } from "./PairingReadiness";
import {
  SECTIONS,
  buildSlidePlan,
  withAssistantSlides,
  type ChartSpec,
  type ObservationRow,
  type SectionId,
  type SlideSpec,
} from "./report-slides";
import type { AnalysisReportQuery } from "./report-types";
import "./analysis.css";

const STORAGE_KEY = "ar03-slide-sections";
const ALL_ON = Object.fromEntries(SECTIONS.map((s) => [s.id, true])) as Sections;

function loadSections(): Sections {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<Sections>;
    return { ...ALL_ON, ...saved };
  } catch {
    return ALL_ON;
  }
}

function saveSections(next: Sections) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Private mode or blocked storage: the choices still work for this visit.
  }
}

// ------------------------------------------------------------------ container
export function AnalysisWorkspace({ code }: { code: string }) {
  const [query, setQuery] = useState<AnalysisReportQuery>({ domain: "both" });
  const [sections, setSections] = useState<Sections>(loadSections);
  const [remarks, setRemarks] = useState<Record<string, string>>({});
  const [nextSteps, setNextSteps] = useState("");
  const [stage, setStage] = useState<ChartSpec[] | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [assistantSlides, setAssistantSlides] = useState<SlideSpec[]>([]);
  const [conversation, setConversation] = useState<{ scope: string; asks: Ask[] }>({
    scope: "",
    asks: [],
  });
  const stageRef = useRef<HTMLDivElement>(null);
  const report = useQuery(analysisReportOptions(code, query));
  const month = report.data?.month ?? "";
  const scope = JSON.stringify([
    code,
    query.month ?? month,
    query.domain ?? "both",
    [...(query.models ?? [])].sort(),
    [...(query.colors ?? [])].sort(),
  ]);
  // Reset only this state when the report selection changes. A late callback from an old
  // panel cannot put an answer back into the new month's conversation.
  if (month && conversation.scope !== scope) setConversation({ scope, asks: [] });
  const asks = conversation.scope === scope ? conversation.asks : [];
  const setAsks = (next: Ask[]) =>
    setConversation((current) => (current.scope === scope ? { scope, asks: next } : current));
  const domain = report.data?.domain ?? "both";
  const wavescan = useQuery({
    ...wavescanOverviewOptions(code, { month, model: query.models, color: query.colors }),
    enabled: Boolean(month) && domain !== "film",
  });
  const film = useQuery({
    ...filmOverviewOptions(code, { month, models: query.models, colors: query.colors }),
    enabled: Boolean(month) && domain !== "wavescan",
  });

  if (report.isPending) return <LoadingState>Loading the report...</LoadingState>;
  if (report.isError)
    return <ApiErrorState error={report.error} retry={() => void report.refetch()} />;

  const wsData = domain !== "film" ? wavescan.data : undefined;
  const filmData = domain !== "wavescan" ? film.data : undefined;
  const toggle = (id: SectionId) => {
    const next = { ...sections, [id]: !sections[id] };
    setSections(next);
    saveSections(next);
  };
  const onExport = async () => {
    setExportError(null);
    const plan = withAssistantSlides(
      buildSlidePlan(
        { report: report.data, wavescan: wsData?.boxes ?? [], film: filmData?.boxes ?? [] },
        { sections, remarks, nextSteps: nextSteps.split("\n"), date: new Date() },
      ),
      assistantSlides,
    );
    const overviewCharts = plan.flatMap((s) =>
      s.kind === "chart" ? s.charts.filter((c) => !c.boxes) : [],
    );
    const html = document.documentElement;
    const wasDark = html.classList.contains("dark");
    try {
      const { exportReport, captureStack, bandPng } = await import("./exportReport");
      // The slides are white: capture the overview charts in the light theme.
      html.classList.remove("dark");
      setStage(overviewCharts);
      const pngs = new Map<string, Awaited<ReturnType<typeof captureStack>>>();
      if (overviewCharts.length) {
        const root = await stageReady(stageRef, overviewCharts.length);
        for (const chart of overviewCharts) {
          const block = root.querySelector<HTMLElement>(
            `[data-chart-id="${CSS.escape(chart.id)}"]`,
          )!;
          const cards = [
            ...block.querySelectorAll<HTMLElement>(
              "section[aria-label$=' Horizontal'], section[aria-label$=' Vertical']",
            ),
          ].filter((el) => el.querySelector("svg.recharts-surface"));
          pngs.set(chart.id, await captureStack(cards));
        }
      }
      if (wasDark) html.classList.add("dark");
      setStage(null);
      await exportReport(
        plan,
        `${report.data.plant_code}-quality-report-${month}.pptx`,
        async (chart) => (chart.boxes ? bandPng(chart) : pngs.get(chart.id)!),
      );
    } catch (error) {
      setExportError(
        `The slides could not be built: ${error instanceof Error ? error.message : String(error)} Try Export again.`,
      );
    } finally {
      if (wasDark) html.classList.add("dark");
      setStage(null);
    }
  };

  return (
    <PointLabelsProvider plant={code}>
      <AnalysisReportView
        report={report.data}
        wavescanData={wsData}
        filmData={filmData}
        sections={sections}
        onToggle={toggle}
        query={query}
        onQuery={(next) => {
          setConversation({ scope: "", asks: [] });
          setQuery(next);
        }}
        remarks={remarks}
        onRemark={(key, value) => setRemarks((r) => ({ ...r, [key]: value }))}
        nextSteps={nextSteps}
        onNextSteps={setNextSteps}
        onExport={() => void onExport()}
        exporting={stage !== null}
        exportError={exportError}
        chartFor={(row) => (
          <ChartBoundary>
            <OverviewChart row={row} wsData={wsData} filmData={filmData} />
          </ChartBoundary>
        )}
        pairing={<PairingReadiness code={code} />}
        assistant={
          <AssistantPanel
            key={scope}
            code={code}
            query={query}
            live={liveNames(report.data.options)}
            asks={asks}
            onAsks={setAsks}
            onAddToSlides={(s) => setAssistantSlides((a) => [...a, s])}
          />
        }
      />
      {stage && (
        <div
          ref={stageRef}
          aria-hidden
          inert
          className="ar03 fixed top-0 bg-white text-foreground"
          style={{ left: -20000, width: 1600 }}
        >
          {stage.map((chart) => {
            const [kind, model, layer] = chart.id.split("|");
            return (
              <div key={chart.id} data-chart-id={chart.id} className="p-2">
                <OverviewChart
                  row={{ domain: kind === "ws" ? "wavescan" : "film", model, layer: layer ?? null }}
                  wsData={wsData}
                  filmData={filmData}
                />
              </div>
            );
          })}
        </div>
      )}
    </PointLabelsProvider>
  );
}

/** Resolves when every staged chart has drawn its Recharts surface. */
function stageReady(ref: RefObject<HTMLDivElement | null>, count: number) {
  return new Promise<HTMLDivElement>((resolve, reject) => {
    const started = Date.now();
    const check = () => {
      const root = ref.current;
      const drawn = root
        ? [...root.querySelectorAll("[data-chart-id]")].filter((b) =>
            [...b.querySelectorAll("svg.recharts-surface")].some(
              (s) => s.getBoundingClientRect().width > 0,
            ),
          ).length
        : 0;
      if (root && drawn >= count) setTimeout(() => resolve(root), 400);
      else if (Date.now() - started > 15000)
        reject(new Error("the charts did not finish drawing."));
      else setTimeout(check, 100);
    };
    check();
  });
}

/** A chart that fails to draw says so; the rest of the page keeps working. */
class ChartBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <p role="alert" className="text-sm text-muted-foreground">
        This Monthly Overview chart could not be drawn. Open the Monthly Overview tab to see it.
      </p>
    ) : (
      this.props.children
    );
  }
}

/** The dashboard's own Monthly Overview chart for one model (x layer). */
function OverviewChart({
  row,
  wsData,
  filmData,
}: {
  row: Pick<ObservationRow, "domain" | "model" | "layer">;
  wsData?: WavescanData;
  filmData?: FilmOverviewData;
}) {
  if (row.domain === "wavescan") {
    if (!wsData) return <LoadingState>Loading the Monthly Overview chart...</LoadingState>;
    return (
      <div className="ar03-overview min-w-0">
        <PlantOverview
          month={wsData.month}
          data={{ ...wsData, boxes: wsData.boxes.filter((b) => b.model_code === row.model) }}
          isPending={false}
          isError={false}
          error={null}
          onRetry={() => {}}
          selectedModels={[row.model]}
        />
      </div>
    );
  }
  if (!filmData) return <LoadingState>Loading the Monthly Overview chart...</LoadingState>;
  const group = groupFilmBoxes(filmData, row.layer as never).find((g) => g.model === row.model);
  return group ? (
    <div className="film-overview ar03-overview min-w-0">
      <FilmOverviewChart {...group} />
    </div>
  ) : null;
}
