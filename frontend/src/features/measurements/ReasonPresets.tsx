import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";

export function ReasonPresets({
  label,
  value,
  onChange,
  presets,
  ariaLabel,
  required = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  presets: readonly string[];
  ariaLabel: string;
  required?: boolean;
}) {
  const field = useRef<HTMLTextAreaElement>(null);
  const [choseOther, setChoseOther] = useState(false);
  const named = presets.filter((preset) => preset !== "Other");
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm">{label}</legend>
      <div className="flex flex-wrap gap-2">
        {presets.map((preset) => {
          const pressed =
            preset === "Other" ? choseOther && !named.includes(value) : value === preset;
          return (
            <Button
              key={preset}
              type="button"
              size="sm"
              variant={pressed ? "default" : "outline"}
              aria-pressed={pressed}
              onClick={() => {
                if (preset === "Other") {
                  setChoseOther(true);
                  onChange("");
                  field.current?.focus();
                  return;
                }
                setChoseOther(false);
                onChange(preset);
              }}
            >
              {preset}
            </Button>
          );
        })}
      </div>
      <label className="block text-xs">
        {required ? "Required" : "Optional"} note
        <textarea
          ref={field}
          aria-label={ariaLabel}
          required={required}
          maxLength={2000}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="mt-1 block min-h-20 w-full rounded-sm border border-border bg-background p-2"
        />
      </label>
    </fieldset>
  );
}
