import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { landingStatusOptions } from "@/api/queries";
import { Simulator } from "@/components/ct/Simulator";
import { LandingScores } from "./LandingScores";
import { AppShell } from "@/components/ct/AppShell";
import { useControlState } from "@/lib/ct/use-control-state";
import { LandingWaves, WaveMotionControl } from "./LandingWaves";
import { useWaveMotion } from "./use-wave-motion";
import { PlantExplorerMap } from "./PlantExplorerMap";
import { PlantPreview } from "./PlantPreview";
import type { Plant } from "@/lib/ct/data";
import type { FactoryDomain } from "./FactoryStage";
import { feedView, usePlantFeeds } from "./plant-feed";
import { ImgColor, ImgOverview } from "./ImgOverview";
import type { FilmMeasure } from "./img-overview-display";

export function Overview() {
  useEffect(() => {
    document.title = "Plant network | Paint Appearance";
  }, []);
  const { state, active, togglePlant, reset } = useControlState();
  const motion = useWaveMotion();
  const feeds = usePlantFeeds();
  const landing = useQuery(landingStatusOptions);
  const [country, setCountry] = useState<string | null>(null);
  const [plant, setPlant] = useState<Plant | null>(null);
  const [hoveredPlant, setHoveredPlant] = useState<string | null>(null);
  const [domain, setDomain] = useState<FactoryDomain>("wave");
  const preview = useRef<HTMLDivElement>(null);
  const explorer = useRef<HTMLDivElement>(null);
  // Overview IMG: the choices outlive the popup, so reopening shows the same report.
  const [imgReport, setImgReport] = useState<"overview" | "color" | null>(null);
  const imgOpen = imgReport !== null;
  const [imgMonth, setImgMonth] = useState<string | null>(null);
  const [imgMeasure, setImgMeasure] = useState<FilmMeasure>("CALCULATED_TOTAL");
  const overviewTrigger = useRef<HTMLButtonElement>(null);
  const colorTrigger = useRef<HTMLButtonElement>(null);
  // Each report closes only itself: a close animation finishing after the other report
  // was opened must not shut that one.
  const closeImg = (kind: "overview" | "color") => {
    setImgReport((open) => (open === kind ? null : open));
    const trigger = kind === "color" ? colorTrigger : overviewTrigger;
    requestAnimationFrame(() => trigger.current?.focus());
  };
  const selectCountry = (next: string | null) => {
    setCountry(next);
    setPlant(null);
  };
  const selectPlant = (next: Plant) => {
    setCountry(next.country);
    setPlant(next);
  };
  useEffect(() => {
    if (!plant || window.innerWidth >= 1280) return;
    const frame = requestAnimationFrame(() =>
      preview.current?.scrollIntoView({
        behavior: motion.reduced ? "instant" : "smooth",
        block: "start",
      }),
    );
    return () => cancelAnimationFrame(frame);
  }, [plant, motion.reduced]);

  return (
    <div className="landing-overview">
      <LandingWaves paused={motion.paused} reduced={motion.reduced} />
      <AppShell state={state} footerControls={<WaveMotionControl {...motion} />}>
        <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
          {plant
            ? `${plant.code} preview opened. Open its dashboard from the preview panel.`
            : country
              ? `${country} selected. Choose a plant from the preview panel.`
              : "Showing all plants."}
        </div>
        {(landing.isPending || landing.isError) && (
          <div className="panel landing-data-state">
            <p role="status">
              {landing.isPending
                ? "Loading plant status… You can still explore the plants."
                : landing.data
                  ? "Plant status could not refresh. Showing the last available data."
                  : "Plant status is unavailable. You can still explore plants and open their dashboards."}
            </p>
            {landing.isError && (
              <button
                type="button"
                onClick={() => void landing.refetch()}
                disabled={landing.isFetching}
              >
                {landing.isFetching ? "Retrying…" : "Retry plant status"}
              </button>
            )}
          </div>
        )}
        <LandingScores
          feeds={feeds}
          active={active}
          selected={plant?.id ?? null}
          onPlant={selectPlant}
          onHighlight={setHoveredPlant}
        />
        <div
          className="plant-explorer"
          ref={explorer}
          data-preview={Boolean(country)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && country) {
              selectCountry(null);
              explorer.current?.querySelector<HTMLButtonElement>("nav button")?.focus();
            }
          }}
        >
          <div className="img-host" data-img-open={imgOpen || undefined}>
            <div className="img-host__map" inert={imgOpen}>
              <PlantExplorerMap
                feeds={feeds}
                country={country}
                selectedPlant={plant?.id ?? null}
                onCountry={selectCountry}
                onPlant={selectPlant}
                reduced={motion.reduced}
                highlighted={hoveredPlant ? [...active, hoveredPlant] : active}
                onHighlight={setHoveredPlant}
                paused={motion.paused}
              />
            </div>
            {imgReport === "overview" && (
              <ImgOverview
                month={imgMonth}
                onMonth={setImgMonth}
                measure={imgMeasure}
                onMeasure={setImgMeasure}
                onClose={() => closeImg("overview")}
                reduced={motion.reduced}
              />
            )}
            {imgReport === "color" && (
              <ImgColor
                month={imgMonth}
                onMonth={setImgMonth}
                onClose={() => closeImg("color")}
                reduced={motion.reduced}
              />
            )}
          </div>
          <div ref={preview} className="plant-explorer__detail">
            {country ? (
              <PlantPreview
                feeds={feeds}
                country={country}
                plant={plant}
                domain={domain}
                onDomain={setDomain}
                onPlant={selectPlant}
                onBack={() => {
                  selectCountry(null);
                  explorer.current?.querySelector<HTMLButtonElement>("nav button")?.focus();
                }}
                reduced={motion.reduced}
                paused={motion.paused}
                highlighted={hoveredPlant}
                onHighlight={setHoveredPlant}
              />
            ) : (
              <Simulator
                active={active}
                onToggle={togglePlant}
                onReset={reset}
                reports={[
                  {
                    key: "overview",
                    label: "Overview IMG",
                    description: "Monthly family averages · all plants",
                    open: imgReport === "overview",
                    onOpen: () => setImgReport("overview"),
                    trigger: overviewTrigger,
                  },
                  {
                    key: "color",
                    label: "IMG Color",
                    description: "Average CF by colour · ranked",
                    open: imgReport === "color",
                    onOpen: () => setImgReport("color"),
                    trigger: colorTrigger,
                  },
                ]}
                feeds={Object.fromEntries(
                  Object.entries(feeds).map(([code, feed]) => [code, feedView(feed)]),
                )}
              />
            )}
          </div>
        </div>
      </AppShell>
    </div>
  );
}
