import { useEffect, useRef } from "react";
import { statusLabel, type OverviewBox } from "./overview-display";
import { wavescanMeasure, wavescanPrimary, wavescanMeasuredDate } from "./wavescan-inspection";
import { pointText, usePointLabelsHere } from "./point-labels";

export function WavescanBoxSummary({ box, close }: { box: OverviewBox; close: () => void }) {
  const panel = useRef<HTMLElement>(null);
  const labelOf = usePointLabelsHere();
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (preference.matches || !panel.current) return;
    const entrance = panel.current.animate(
      [
        { opacity: 0, transform: "translateY(3px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      { duration: 180, easing: "ease-out" },
    );
    const cancel = () => entrance.cancel();
    preference.addEventListener("change", cancel);
    return () => {
      preference.removeEventListener("change", cancel);
      entrance.cancel();
    };
  }, []);
  const primary = wavescanPrimary(box);
  const details = [
    ...primary.map((field) => [field.label, field.raw ?? "Not set"]),
    ["Q1", box.q1],
    ["Median", box.median],
    ["Q3", box.q3],
    ["Lower whisker", box.whisker_lo],
    ["Upper whisker", box.whisker_hi],
    ["Statistical outliers", box.outliers.join(", ") || "None"],
  ];
  return (
    <section ref={panel} className="wavescan-summary" aria-label="WaveScan box detail">
      <div className="wavescan-summary-heading">
        <div>
          <h5 className="font-semibold">{box.color_name}</h5>
          <p>
            WaveScan · {box.orient} · CF ·{" "}
            <strong data-wavescan-status={box.status ?? "NONE"}>{statusLabel(box.status)}</strong>
          </p>
        </div>
        <button type="button" className="wavescan-close" onClick={close}>
          Close detail
        </button>
      </div>
      <dl className="wavescan-summary-primary">
        {primary.slice(0, 3).map((field) => (
          <div key={field.label}>
            <dt>{field.label}</dt>
            <dd className="num">
              {field.display}
              {field.raw != null && <span> CF</span>}
            </dd>
          </div>
        ))}
      </dl>
      <section className="wavescan-published-standard" aria-label="Published standard">
        <h6>Published standard</h6>
        <dl>
          {primary.slice(3).map((field) => (
            <div key={field.label}>
              <dt>{field.label}</dt>
              <dd className="num">
                {field.display}
                {field.raw != null && <span> CF</span>}
              </dd>
            </div>
          ))}
        </dl>
      </section>
      <p className="text-sm text-muted-foreground">
        Box status follows its average; a Pass or Acceptable box may contain readings below Minimum.
      </p>
      <details>
        <summary>Below Minimum</summary>
        {box.below_minimum.length ? (
          <ol
            className="wavescan-reading-list"
            tabIndex={0}
            aria-label="Below Minimum reading details"
          >
            {box.below_minimum.map((reading) => (
              <li key={reading.measurement_id}>
                <dl className="wavescan-reading-fields">
                  <div>
                    <dt>Measurement date</dt>
                    <dd>{wavescanMeasuredDate(reading.measured_date)}</dd>
                  </div>
                  <div>
                    <dt>Point / zone</dt>
                    <dd>
                      {reading.checkzone
                        ? pointText(
                            labelOf("wavescan", box.model_code, reading.checkzone),
                            reading.checkzone,
                          )
                        : "Zone unavailable"}
                    </dd>
                  </div>
                  <div>
                    <dt>CF value</dt>
                    <dd className="num">{wavescanMeasure(reading.cf)} CF</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ol>
        ) : (
          <p className="py-3">No readings below Minimum</p>
        )}
      </details>
      <details>
        <summary>Detailed measurements</summary>
        <p className="text-muted-foreground">
          Original values in CF. Statistical outliers describe the distribution.
        </p>
        <dl className="wavescan-summary-details">
          {details.map(([label, raw]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className="num">{raw}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
