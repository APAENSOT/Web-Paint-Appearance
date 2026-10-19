import type { BoardItem, Preview } from "./comparison-board";
import { Contributions, ProfilePair } from "./StudioCharts";
export function MonthlyProfile({
  item,
  data,
  hidden,
  colors,
}: {
  item: BoardItem;
  data: Preview;
  hidden: string[];
  colors: string[];
}) {
  const visible = colors.filter((c) => !hidden.includes(c));
  return (
    <section className="studio-item-profile" aria-label={`${item.name} profile card`}>
      <div className="studio-toolbar">
        <h3>
          {item.kind === "month" ? item.months[0] : item.name} / {data.model}
        </h3>
        <span className="cv-muted">{item.months.join(" + ")}</span>
      </div>
      {!visible.length && (
        <p>No visible profile colours. Restore all to display returned series.</p>
      )}
      {visible.map((color) => {
        const lines = data.profiles
          .filter((p) => p.color === color)
          .map((p) => ({
            id: `p${p.point_no}-${p.code}`,
            label: `${p.point_no}. ${p.code}`,
            orientation: p.orientation,
            values: p.metrics.map((m) => {
              const monthly = m.monthly.find((v) => v.month === item.months[0]);
              return {
                metric: m.metric,
                value: item.kind === "month" ? (monthly?.mean ?? null) : m.mean,
                detail: (
                  <>
                    <p>
                      {data.model} / {color} / {p.point_no}. {p.code}
                    </p>
                    {item.kind === "group" ? (
                      <Contributions value={m} />
                    ) : (
                      <p>
                        Month {item.months[0]} / Mean:{" "}
                        <strong className="num">{monthly?.mean ?? "Not measured"}</strong> / n{" "}
                        {monthly?.n ?? "Unavailable"}
                      </p>
                    )}
                  </>
                ),
              };
            }),
          }));
        return (
          <section
            className="monthly-colour-profile"
            key={color}
            aria-label={`${color} focused profile`}
          >
            <h3>{color}</h3>
            <ProfilePair
              focusLocations
              key={`${item.id}-${color}`}
              title={`${item.name} / ${color}`}
              lines={lines}
            />
          </section>
        );
      })}
      {data.unaligned_reading_count
        .filter((c) => c.n > 0)
        .map((c) => (
          <p className="cv-muted" key={c.month}>
            {c.month}: {c.n} historical unaligned source rows, excluded from location profiles.
          </p>
        ))}
    </section>
  );
}
