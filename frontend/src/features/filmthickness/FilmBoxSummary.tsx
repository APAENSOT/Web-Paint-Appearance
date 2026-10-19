import {
  FILM_LAYERS,
  displayMean,
  measuredDate,
  noOutsideLimitText,
  orientationLabel,
  pointKey,
  readingSide,
  scopeLabel,
  specSegments,
  statusPresentation,
  type FilmOverviewBox,
  type FilmColorSequenceEntry,
} from "./film-overview-display";
import { pointText, usePointLabelsHere } from "@/features/measurements/point-labels";

export function FilmBoxSummary({
  box,
  close,
  ladder,
}: {
  box: FilmOverviewBox;
  close: () => void;
  ladder?: FilmColorSequenceEntry["ladder"];
}) {
  const status = statusPresentation(box);
  const labelOf = usePointLabelsHere();
  const published =
    box.standard_scope === "NONE"
      ? []
      : [
          { field: "lo", label: box.lo_label, raw: box.lo },
          { field: "hi", label: box.hi_label, raw: box.hi },
          { field: "target", label: box.target_label, raw: box.target },
        ].filter((spec) => spec.label !== null);
  const primary = [
    ["Average", box.mean],
    ["Observed minimum", box.box_min],
    ["Observed maximum", box.box_max],
  ];
  const statistics = [
    ["Q1", box.q1],
    ["Median", box.median],
    ["Q3", box.q3],
    ["Lower whisker", box.whisker_lo],
    ["Upper whisker", box.whisker_hi],
    ["Statistical outliers", box.outliers.join(", ") || "None"],
  ];
  return (
    <section role="region" aria-label="Box detail" className="film-detail">
      <div className="film-summary-heading">
        <div>
          <h5 className="font-semibold">{box.color_name}</h5>
          <p>
            {FILM_LAYERS.find((layer) => layer.code === box.layer_code)?.label ?? box.layer_code} ·{" "}
            {orientationLabel(box.orient)} · µm ·{" "}
            <span data-status={status.colour} className="film-status-badge">
              {status.text}
            </span>
          </p>
        </div>
        <button type="button" className="film-close-summary" onClick={close}>
          Close detail
        </button>
      </div>
      <dl className="film-summary-primary">
        {primary.map(([label, raw]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className="num">
              {displayMean(raw)} <span>µm</span>
            </dd>
          </div>
        ))}
      </dl>
      <section className="film-published-standard" aria-label="Published standard">
        <h6>Published standard</h6>
        <p>{scopeLabel[box.standard_scope]}</p>
        <dl>
          {published.map((spec) => (
            <div key={spec.field}>
              <dt>{spec.label}</dt>
              <dd className="num">
                {spec.raw ?? "Not set"}
                {spec.raw !== null && " µm"}
              </dd>
            </div>
          ))}
        </dl>
        {ladder === "NO_BASE_STANDARD" && (
          <p className="film-ordering-note">No Base standard for ordering</p>
        )}
      </section>
      <p className="text-sm text-muted-foreground">
        Box status follows its average; a Pass box may contain readings outside a limit.
      </p>
      <details className="film-summary-disclosure">
        <summary>Outside-limit readings</summary>
        {box.out_of_spec.length ? (
          <ol className="film-reading-list" tabIndex={0} aria-label="Outside-limit reading details">
            {box.out_of_spec.map((point, index) => (
              <li key={pointKey(box, point, index)}>
                <dl className="film-reading-fields">
                  <div>
                    <dt>Measurement date</dt>
                    <dd>{measuredDate(point.measured_date)}</dd>
                  </div>
                  <div>
                    <dt>Point</dt>
                    <dd>
                      {pointText(
                        labelOf("film", box.model_code, point.point_code),
                        point.point_code,
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Value (µm)</dt>
                    <dd className="num">{point.value}</dd>
                  </div>
                  <div>
                    <dt>Published limit</dt>
                    <dd>{readingSide(box, point)}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ol>
        ) : (
          <p className="py-3">{noOutsideLimitText(box)}.</p>
        )}
      </details>
      <details className="film-summary-disclosure">
        <summary>Detailed measurements</summary>
        <p>
          {scopeLabel[box.standard_scope]} · {box.family_name ?? "No family assigned"}
        </p>
        <dl className="film-detail-values">
          {[...primary, ...statistics].map(([label, raw]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className="num">{raw}</dd>
            </div>
          ))}
          {specSegments(box, 0, 0).map((spec) => (
            <div key={spec.field}>
              <dt>{spec.label}</dt>
              <dd className="num">{spec.raw}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
