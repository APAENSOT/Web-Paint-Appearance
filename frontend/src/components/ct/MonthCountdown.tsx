import { useEffect, useState } from "react";

/* Countdown to the end of the current calendar month — the plant reporting
   cut-off. Target is 00:00 of the 1st of next month; values re-derive from
   `now` on every tick, so a month rollover needs no extra state. */

const UNITS = [
  { key: "weeks", label: "W" },
  { key: "days", label: "D" },
  { key: "hours", label: "H" },
  { key: "minutes", label: "M" },
] as const;

function useTimeToMonthEnd() {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const d = new Date(now);
  const target = new Date(d.getFullYear(), d.getMonth() + 1, 1).getTime();
  const totalMinutes = Math.floor(Math.max(0, target - now) / 60_000);

  return {
    weeks: Math.floor(totalMinutes / (7 * 24 * 60)),
    days: Math.floor((totalMinutes % (7 * 24 * 60)) / (24 * 60)),
    hours: Math.floor((totalMinutes % (24 * 60)) / 60),
    minutes: totalMinutes % 60,
  };
}

export function MonthCountdown() {
  const t = useTimeToMonthEnd();
  return (
    <div className="panel flex items-center gap-3 px-3 py-1.5">
      <p className="eyebrow">month ends in</p>
      <div className="flex items-stretch divide-x divide-[color:var(--hairline)]">
        {UNITS.map((u) => (
          <div key={u.key} className="px-2 text-center">
            <p className="num text-sm font-semibold leading-none">{t[u.key]}</p>
            <p className="eyebrow mt-0.5">{u.label}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
