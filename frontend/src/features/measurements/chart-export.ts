export type Cell = string | number | null | undefined;
export type TableData = { columns: string[]; rows: Cell[][] };

const csvCell = (v: Cell) => {
  const s = v == null ? "" : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
};
export const toCsv = ({ columns, rows }: TableData) =>
  [columns, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");

export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const fileName = (title: string, ext: string) =>
  `${title.replace(/[^\w-]+/g, "-").replace(/^-|-$/g, "")}.${ext}`;

// Chart marks colour themselves with var(--token); an SVG drawn as an image cannot see those.
const BAKED = [
  "fill",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "fill-opacity",
  "opacity",
  "stroke-dasharray",
  "font-size",
  "font-family",
  "font-weight",
  "text-anchor",
  "paint-order",
  "visibility",
];

/** Title + the chart SVG + an optional colour legend, at 2x, on the page background. */
export async function chartPng(
  svg: SVGSVGElement,
  title: string,
  legend: Array<{ label: string; color: string }> = [],
): Promise<Blob> {
  const { width, height } = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const from = [svg, ...svg.querySelectorAll("*")];
  const to = [clone, ...clone.querySelectorAll("*")];
  from.forEach((el, i) => {
    const css = getComputedStyle(el);
    const target = to[i] as SVGElement;
    for (const prop of BAKED) target.style.setProperty(prop, css.getPropertyValue(prop));
  });
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }),
  );
  try {
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error("The chart could not be drawn as an image."));
      img.src = url;
    });
    const page = getComputedStyle(document.body);
    const pad = 24;
    const head = 40;
    const perRow = Math.max(1, Math.floor(width / 200));
    const legendH = legend.length ? Math.ceil(legend.length / perRow) * 22 + 12 : 0;
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = (width + pad * 2) * scale;
    canvas.height = (head + height + legendH + pad * 2) * scale;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(scale, scale);
    ctx.fillStyle = page.backgroundColor;
    ctx.fillRect(0, 0, width + pad * 2, head + height + legendH + pad * 2);
    ctx.fillStyle = page.color;
    ctx.font = `600 16px ${page.fontFamily}`;
    ctx.fillText(title, pad, pad + 16);
    ctx.drawImage(img, pad, pad + head, width, height);
    ctx.font = `12px ${page.fontFamily}`;
    legend.forEach(({ label, color }, i) => {
      const x = pad + (i % perRow) * 200;
      const y = pad + head + height + 16 + Math.floor(i / perRow) * 22;
      ctx.fillStyle = color;
      ctx.fillRect(x, y - 8, 16, 4);
      ctx.fillStyle = page.color;
      ctx.fillText(label, x + 24, y - 2);
    });
    return await new Promise((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("PNG encoding failed."))),
        "image/png",
      ),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}
