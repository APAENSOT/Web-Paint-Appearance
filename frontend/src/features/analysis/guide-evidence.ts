import type { AssistantAnswer } from "./report-types";

/** Reading instructions only. Findings, grades and quantities always come from the API. */
export function evidenceReading(evidence: AssistantAnswer["evidence"]) {
  if (evidence.kind === "bar" && evidence.columns.includes("ρ"))
    return [
      "Which bands move with CF",
      "Larger absolute values show a stronger association with CF. The printed sign shows direction. An association does not establish a cause.",
    ];
  const readings: Record<string, [string, string]> = {
    bar: [
      "Where to focus",
      "Read each full label and its printed value. Bar lengths compare measurements or counts on the same scale; the status describes the result.",
    ],
    trend: [
      "How readings changed through the month",
      "Follow the daily mean from left to right. Dashed lines mark the supplied limits; a mean inside a limit does not mean every reading passed.",
    ],
    shift: [
      "What moved since the previous month",
      "Compare the two dated values, then read the change and supplied verdict. Measurements share a scale only when they use the same unit.",
    ],
    heatmap: [
      "Which combinations need attention",
      "Read across a row to compare its layers or parameters. Each cell names its status, so colour is not the only way to read the result.",
    ],
    grid: [
      "Where the issue repeats",
      "Follow the same row across periods. Repeated status labels show when the issue appears again; a missing measurement is not a pass.",
    ],
    trend_monthly: [
      "The longer view",
      "Read months from left to right and compare the same measurement across months. Missing periods do not establish an improvement.",
    ],
    boxplot_pair: [
      "How the two groups compare",
      "Compare the middle lines for typical readings, then the boxes and whiskers for spread. Read the supplied verdict before treating a difference as meaningful.",
    ],
    boxplot_group: [
      "How the groups compare",
      "Compare the middle lines and spread on the same scale. Use the labels and supplied verdict to identify which group needs attention.",
    ],
    mirrored_bar: [
      "How the two sides compare",
      "Compare left and right for the same measuring point. Read the counts and measured totals together when the two sides have different sample sizes.",
    ],
    point_bars: [
      "Where the cars differ",
      "Compare the two cars at the same measuring point. Use the supplied limits and labels to distinguish a difference from an out-of-standard reading.",
    ],
    breakdown: [
      "What contributes to the result",
      "Read each labelled part alongside its count. This describes the measured problem; it does not establish its process cause.",
    ],
    car_bars: [
      "How the issue is distributed across cars",
      "Read points out alongside points measured for each car. Different measured totals matter when comparing cars.",
    ],
    distribution: [
      "Where the readings sit against the limits",
      "Taller bars contain more readings in that value range. Dashed lines are the supplied limits; the solid line marks the mean.",
    ],
    weekly_strip: [
      "When the readings were collected",
      "Compare the labelled weeks and their counts. A week without measurements cannot show whether quality improved.",
    ],
    limit_card: [
      "The standard for this selection",
      "Read the parameter, units and each supplied limit together. These are the reference values, not a new measurement.",
    ],
    stat: [
      "What data can be compared",
      "Read the labelled counts together. Only cars measured on both instruments can support a paired comparison.",
    ],
    spectrum: [
      "Which appearance bands stand out",
      "Compare the labelled bands against their supplied references. The bands describe different features, so use the interpretation rather than comparing raw heights alone.",
    ],
    scatter: [
      "How the measurements move together",
      "Each point is a measured pair. A pattern can show an association; it does not prove one measurement causes the other.",
    ],
  };
  return (
    readings[evidence.kind ?? ""] ?? [
      "The supporting measurements",
      "Read the row labels, units and supplied status together. A missing value is not a zero or a pass.",
    ]
  );
}
