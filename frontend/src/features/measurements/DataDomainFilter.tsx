import type { DataDomain } from "./domain-tags";

export function DataDomainFilter({
  value,
  onChange,
}: {
  value: DataDomain;
  onChange: (value: DataDomain) => void;
}) {
  return (
    <label className="block text-xs font-medium">
      Paint Appearance
      <select
        aria-label="Paint Appearance"
        value={value}
        onChange={(event) => onChange(event.target.value as DataDomain)}
        className="mt-1 block min-h-10 rounded-md border border-border bg-background px-3 py-2 text-sm"
      >
        <option value="both">Both</option>
        <option value="wavescan">WaveScan</option>
        <option value="film">Film Thickness</option>
      </select>
    </label>
  );
}
