import { ChevronDown } from "lucide-react";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { metrics, type Domain } from "./comparison-state";
import type { ComparisonSession } from "./useComparisonVehicles";
function Section({
  label,
  children,
  open = true,
}: {
  label: string;
  children: React.ReactNode;
  open?: boolean;
}) {
  return (
    <details className="border-b border-border py-3" open={open}>
      <summary className="eyebrow flex cursor-pointer list-none items-center justify-between">
        {label}
        <ChevronDown size={14} />
      </summary>
      <div className="mt-3 space-y-2">{children}</div>
    </details>
  );
}
export function ComparisonFilters({ session }: { session: ComparisonSession }) {
  const { state: s, dispatch: d, options, candidates, modelValid } = session;
  const data = modelValid ? (candidates.data ?? options.data) : options.data;
  const toggle = (key: "months" | "colors" | "periods", value: string) => {
    const values = s[key] ?? [];
    const next = values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
    // Omitting months means latest in T79; retain one explicit measured month.
    if (key === "months" && !next.length) return;
    d({ type: "filter", key, value: next });
  };
  return (
    <div aria-label="Vehicle comparison filters">
      <Section label="Paint Functional">
        {(
          [
            ["WAVESCAN", "WaveScan"],
            ["FILMTHICKNESS", "Film Thickness"],
          ] as [Domain, string][]
        ).map(([domain, label]) => (
          <label className="cv-choice" key={domain}>
            <input
              type="radio"
              name="comparison-domain"
              checked={s.domain === domain}
              onChange={() => d({ type: "domain", domain })}
            />
            {label}
          </label>
        ))}
      </Section>
      {options.isPending ? (
        <LoadingState>Loading measured options...</LoadingState>
      ) : options.isError ? (
        <ApiErrorState error={options.error} retry={() => void options.refetch()} />
      ) : (
        <>
          <Section label="Vehicle Model">
            {data?.model_options.map((model) => (
              <label className="cv-choice" key={model}>
                <input
                  type="radio"
                  name="comparison-model"
                  checked={s.model === model}
                  onChange={() => d({ type: "model", model })}
                />
                {model}
              </label>
            ))}
            {!data?.model_options.length && <p className="cv-muted">No domain data.</p>}
          </Section>
          <Section label="Measured Months">
            {data?.available_months.map((month) => (
              <label className="cv-choice" key={month}>
                <input
                  aria-label={`Measured month ${month}`}
                  type="checkbox"
                  checked={!!s.months?.includes(month)}
                  onChange={() => toggle("months", month)}
                />
                <span className="num">{month}</span>
              </label>
            ))}
          </Section>
          <Section label="Measured Weeks" open={false}>
            {Array.from(new Set(data?.week_options.map((week) => week.month) ?? [])).map(
              (month) => (
                <fieldset key={month} className="space-y-2">
                  <legend className="cv-muted num mb-2">{month}</legend>
                  {data?.week_options
                    .filter((w) => w.month === month)
                    .map((w) => {
                      const period = `${w.month}-W${w.week}`;
                      return (
                        <label className="cv-choice" key={period}>
                          <input
                            type="checkbox"
                            checked={s.periods.includes(period)}
                            onChange={() => toggle("periods", period)}
                          />
                          {period}
                        </label>
                      );
                    })}
                </fieldset>
              ),
            )}
            {!s.model && <p className="cv-muted">Choose a model to see measured weeks.</p>}
          </Section>
          <Section label="Paint Colours" open={false}>
            <p className="cv-muted">None selected means all colours.</p>
            {data?.color_options.map((color) => (
              <label className="cv-choice" key={color}>
                <input
                  type="checkbox"
                  checked={s.colors.includes(color)}
                  onChange={() => toggle("colors", color)}
                />
                {color}
              </label>
            ))}
          </Section>
        </>
      )}
      <Section label="Metric">
        <select
          aria-label="Comparison metric"
          className="cv-input"
          value={s.metric}
          onChange={(e) => d({ type: "metric", metric: e.target.value as typeof s.metric })}
        >
          {metrics[s.domain].map((metric) => (
            <option key={metric} value={metric}>
              {metric}
            </option>
          ))}
        </select>
      </Section>
    </div>
  );
}
