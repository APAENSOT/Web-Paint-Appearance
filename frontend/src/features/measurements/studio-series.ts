import type { Preview, BoardItem } from "./comparison-board";
import type { BoxEntry } from "./StudioCharts";
export function monthlyEntries(
  data: Preview,
  item: BoardItem,
  visible: (color: string) => boolean,
  colors: string[] = [...new Set(data.group_means.map((g) => g.color))],
): BoxEntry[] {
  const boxes: BoxEntry[] = data.month_boxes.flatMap((month) => {
    const monthEntries: BoxEntry[] = [...month.wavescan_boxes, ...month.film_boxes]
      .filter((box) => visible(box.color_name))
      .map((box, i) => ({
        key: `${item.id}-${month.month}-${i}`,
        itemId: item.id,
        itemName: item.name,
        month: month.month,
        label: `${item.kind === "group" ? `${item.name} / ` : ""}${month.month} / ${box.model_code} / ${box.color_name}`,
        color: box.color_name,
        caption: month.month,
        orientation:
          box.orient === "Horizontal" || box.orient === "H" ? ("H" as const) : ("V" as const),
        n: box.n,
        box,
      }));
    // Keep caller month order, returned boxes and domain colour order. Explicit gaps
    // occupy this month's slot rather than being moved to the end of the board.
    for (const color of colors.filter(visible))
      for (const orientation of ["H", "V"] as const) {
        const series = data.group_means.find(
          (g) => g.color === color && g.orientation === orientation,
        );
        if (!monthEntries.some((e) => e.orientation === orientation && e.color === color))
          monthEntries.push({
            key: `${item.id}-gap-${month.month}-${color}-${orientation}`,
            itemId: item.id,
            itemName: item.name,
            month: month.month,
            label: `${item.name} / ${month.month} / ${data.model} / ${color}`,
            color,
            caption: month.month,
            orientation,
            n: series?.monthly.find((m) => m.month === month.month)?.n,
          });
      }
    return monthEntries;
  });
  if (item.kind === "group")
    boxes.push(
      ...data.group_means
        .filter((g) => visible(g.color))
        .map((group, i) => ({
          key: `${item.id}-mean-${i}`,
          itemId: item.id,
          itemName: item.name,
          label: `${item.name} / ${data.model} / ${group.color}`,
          color: group.color,
          caption: item.name,
          orientation: group.orientation,
          group,
          selected: item.months.length,
        })),
    );
  if (!boxes.length && !data.group_means.length && !colors.length)
    for (const month of data.months)
      for (const orientation of ["H", "V"] as const)
        boxes.push({
          key: `${item.id}-${month}-${orientation}`,
          label: `${data.model} / ${month}`,
          orientation,
        });
  return boxes;
}
