/**
 * RO17 (D-RO17-16): a point is shown by the plant's own label first, its code
 * second. The label comes from GET /plants/{plant}/point-labels; a point the
 * list does not hold shows its code, so nothing is ever blank.
 */
import { createContext, createElement, useContext, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { pointLabelsOptions } from "@/api/queries";
import type { components } from "@/api/types";

type Item = components["schemas"]["PointLabelItem"];
export type PointDomain = Item["domain"];
/** `domain` null: whichever one domain holds this model x code (a review row
 * does not say its domain). Two domains with different labels give the code. */
export type LabelOf = (
  domain: PointDomain | null,
  model: string | null | undefined,
  code: string,
) => string;

export function makeLabelOf(items: readonly Item[]): LabelOf {
  const byKey = new Map(
    items.map((item) => [`${item.domain}|${item.model_code}|${item.code}`, item.label]),
  );
  return (domain, model, code) => {
    if (domain) return byKey.get(`${domain}|${model}|${code}`) ?? code;
    const found = new Set(
      (["wavescan", "film"] as const)
        .map((d) => byKey.get(`${d}|${model}|${code}`))
        .filter(Boolean),
    );
    return found.size === 1 ? [...found][0]! : code;
  };
}

/** "Label · code CODE"; the code once when the label is the code. RO17-FIX
 * (D-RO17F-3): "code" in words, so two numbers never read as one name. */
export function pointText(label: string, code: string): string {
  return label === code ? code : `${label} · code ${code}`;
}

/** The plant's labels; the code until they arrive or when the read fails. */
export function usePointLabels(plant: string | null | undefined): LabelOf {
  const labels = useQuery({ ...pointLabelsOptions(plant ?? ""), enabled: Boolean(plant) });
  return useMemo(() => makeLabelOf(labels.data?.items ?? []), [labels.data]);
}

/** For views too deep to be handed a plant (the overview box summaries). With
 * no provider above, a point shows its code. */
const LabelsContext = createContext<LabelOf>(makeLabelOf([]));
export function PointLabelsProvider({
  plant,
  children,
}: {
  plant: string | null | undefined;
  children: ReactNode;
}) {
  return createElement(LabelsContext.Provider, { value: usePointLabels(plant) }, children);
}
export const usePointLabelsHere = () => useContext(LabelsContext);
