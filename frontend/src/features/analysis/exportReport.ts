/**
 * AR03: the slide plan as a .pptx, in the plant's "Quality Report" template.
 *
 * The template is recreated in code from the owner's reference deck: 16:9,
 * Arial Nova, Ford blue, the Ford oval top-right, the "IMG VME Paint" header
 * over the title, the blue finding band, the page number and the "Secret"
 * label (positions in inches, as measured in the reference). The two logos
 * were taken from that deck with the owner's approval (2026-10-14).
 *
 * Model charts are the dashboard's own Monthly Overview cards, captured from
 * the page; band charts are the report's SVG boxplot.
 */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import PptxGenJS from "pptxgenjs";
import { CHART_H, CHART_W, ReportBoxPlot } from "./ReportBoxPlot";
import { HEADER, type ChartSpec, type SlideSpec } from "./report-slides";

export type Png = { data: string; width: number; height: number };
export type PngFor = (chart: ChartSpec) => Promise<Png>;
export type Brand = { oval: string; script: string };

const W = 13.333;
const FONT = "Arial Nova";
const BLUE = "00095B"; // theme dk1 (tx1)
const ACCENT = "066FEF"; // theme accent1
const GREY = "B9BCBD";
const WHITE = "FFFFFF";
// The chart bed between the title row and the finding band.
const BED = { x: 0.41, y: 1.38, w: W - 0.83, h: 5.12 };

// ------------------------------------------------------------------ capture
// Marks colour themselves with var(--token); an SVG drawn as an image cannot see those.
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
  "dominant-baseline",
  "visibility",
];

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("A chart could not be drawn as an image."));
    img.src = src;
  });
}

function svgImage(svg: SVGSVGElement, width: number, height: number) {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  const from = [svg, ...svg.querySelectorAll("*")];
  const to = [clone, ...clone.querySelectorAll("*")];
  from.forEach((el, i) => {
    const css = getComputedStyle(el);
    for (const prop of BAKED)
      (to[i] as SVGElement).style.setProperty(prop, css.getPropertyValue(prop));
  });
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const xml = new XMLSerializer().serializeToString(clone);
  return loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`);
}

/**
 * One on-page card as a PNG: every SVG it holds plus its HTML text (the Film
 * chart writes colour names and status words in HTML under its SVG) and its
 * dashed legend strokes, at 2x on white.
 */
export async function captureElement(el: HTMLElement, scale = 2): Promise<Png> {
  const base = el.getBoundingClientRect();
  const width = Math.ceil(base.width);
  const height = Math.ceil(base.height);
  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(scale, scale);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  for (const svg of el.querySelectorAll("svg")) {
    const r = svg.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const img = await svgImage(svg, r.width, r.height);
    ctx.drawImage(img, r.left - base.left, r.top - base.top, r.width, r.height);
  }
  for (const node of el.querySelectorAll<HTMLElement>("span, li")) {
    const css = getComputedStyle(node);
    const r = node.getBoundingClientRect();
    if (css.borderTopStyle !== "dashed" || r.height > 3) continue;
    ctx.strokeStyle = css.borderTopColor;
    ctx.setLineDash([3, 2]);
    ctx.beginPath();
    ctx.moveTo(r.left - base.left, r.top - base.top + 0.5);
    ctx.lineTo(r.right - base.left, r.top - base.top + 0.5);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    const value = node.textContent ?? "";
    // Screen-reader text is clipped to 1px, but its words still measure; skip it.
    if (!parent || parent.closest("svg, .sr-only") || !value.trim()) continue;
    const css = getComputedStyle(parent);
    if (css.visibility === "hidden" || css.display === "none") continue;
    ctx.font = `${css.fontWeight} ${css.fontSize} ${css.fontFamily}`;
    ctx.fillStyle = css.color;
    ctx.textBaseline = "alphabetic";
    // One rect per word, so wrapped labels land on their own lines.
    for (const m of value.matchAll(/\S+/g)) {
      range.setStart(node, m.index!);
      range.setEnd(node, m.index! + m[0].length);
      const r = range.getBoundingClientRect();
      if (r.width < 1) continue;
      ctx.fillText(m[0], r.left - base.left, r.bottom - base.top - r.height * 0.22);
    }
  }
  return { data: canvas.toDataURL("image/png"), width, height };
}

/** Several cards (Horizontal over Vertical) as one PNG. */
export async function captureStack(els: HTMLElement[], gap = 12): Promise<Png> {
  const pngs: Png[] = [];
  for (const el of els) pngs.push(await captureElement(el));
  const width = Math.max(...pngs.map((p) => p.width));
  const height = pngs.reduce((sum, p) => sum + p.height, 0) + gap * (pngs.length - 1);
  const canvas = document.createElement("canvas");
  canvas.width = width * 2;
  canvas.height = height * 2;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  let y = 0;
  for (const png of pngs) {
    ctx.drawImage(await loadImage(png.data), 0, y * 2, png.width * 2, png.height * 2);
    y += png.height + gap;
  }
  return { data: canvas.toDataURL("image/png"), width, height };
}

/** A band chart: the report's own SVG boxplot, drawn off-page. */
export async function bandPng(chart: ChartSpec): Promise<Png> {
  const svg = renderToStaticMarkup(
    createElement(ReportBoxPlot, { boxes: chart.boxes ?? [], title: chart.title, forImage: true }),
  );
  const img = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
  const canvas = document.createElement("canvas");
  canvas.width = CHART_W * 2;
  canvas.height = CHART_H * 2;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return { data: canvas.toDataURL("image/png"), width: CHART_W, height: CHART_H };
}

/** A bundled image as a PNG data URL (PowerPoint's SVG support varies). */
async function rasterAsset(url: string, width: number, height: number): Promise<string> {
  const img = await loadImage(url);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas.getContext("2d")!.drawImage(img, 0, 0, width, height);
  return canvas.toDataURL("image/png");
}

export async function loadBrand(): Promise<Brand> {
  const [oval, script] = await Promise.all([
    rasterAsset(new URL("./assets/ford-oval.svg", import.meta.url).href, 720, 360),
    rasterAsset(new URL("./assets/ford-script.png", import.meta.url).href, 401, 203),
  ]);
  return { oval, script };
}

// ------------------------------------------------------------------ deck
const text = (slide: PptxGenJS.Slide, value: string, opts: PptxGenJS.TextPropsOptions) =>
  slide.addText(value, { fontFace: FONT, color: BLUE, margin: 0, ...opts });

/** The master: Ford oval, page number, "Secret" (every slide). */
function master(slide: PptxGenJS.Slide, brand: Brand, page: number, onBand: boolean) {
  slide.addImage({ data: brand.oval, x: 12.33, y: 0.24, w: 0.72, h: 0.36 });
  text(slide, "Secret", { x: 0.41, y: 7.0, w: 0.6, h: 0.24, fontSize: 8, color: GREY });
  text(slide, String(page), {
    x: 12.5,
    y: 7.0,
    w: 0.45,
    h: 0.3,
    fontSize: 8,
    align: "right",
    color: onBand ? WHITE : BLUE,
  });
}

/** Content layout: header over the title, the title, and the blue finding band. */
function content(slide: PptxGenJS.Slide, title: string, finding: string) {
  text(slide, HEADER, { x: 0.43, y: 0.31, w: 4.96, h: 0.22, fontSize: 9, color: ACCENT });
  text(slide, title, { x: 0.41, y: 0.55, w: 7.2, h: 0.75, fontSize: 24, valign: "middle" });
  slide.addShape("rect", {
    x: 0.2,
    y: 6.6,
    w: 12.94,
    h: 0.75,
    fill: { color: BLUE },
    line: { color: BLUE },
  });
  text(slide, finding, {
    x: 0.35,
    y: 6.62,
    w: 12.0,
    h: 0.42,
    fontSize: 14,
    color: WHITE,
    valign: "middle",
    fit: "shrink",
  });
}

/** Summary layout: "VME PAINT" header and the title with its colon, as slide 8. */
function summaryHead(slide: PptxGenJS.Slide, title: string) {
  text(slide, "VME PAINT", { x: 0.43, y: 0.31, w: 5.95, h: 0.22, fontSize: 9, color: ACCENT });
  text(slide, `${title} :`, { x: 0.43, y: 0.59, w: 7, h: 0.5, fontSize: 24 });
}

const fit = (png: Png, box: { x: number; y: number; w: number; h: number }) => {
  const k = Math.min(box.w / png.width, box.h / png.height);
  const w = png.width * k;
  return { x: box.x + (box.w - w) / 2, y: box.y, w, h: png.height * k };
};

const table = (x: number, y: number, w: number, fontSize: number, colW?: number[]) => ({
  x,
  y,
  w,
  colW,
  fontSize,
  fontFace: FONT,
  color: BLUE,
  autoPage: true,
  autoPageRepeatHeader: true,
  border: { type: "solid" as const, pt: 0.5, color: "8C8C8C" },
});
const rows = ([head, ...body]: string[][]): PptxGenJS.TableRow[] => [
  head.map((t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: BLUE } } })),
  ...body.map((r) => r.map((t) => ({ text: t }))),
];

export async function buildDeck(
  plan: SlideSpec[],
  pngFor: PngFor,
  brand: Brand,
): Promise<PptxGenJS> {
  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in, as the reference
  pptx.theme = { headFontFace: FONT, bodyFontFace: FONT };
  for (const [index, spec] of plan.entries()) {
    const slide = pptx.addSlide();
    const page = index + 1;
    if (spec.kind === "title") {
      master(slide, brand, page, false);
      text(slide, spec.date, { x: 0.4, y: 0.29, w: 2.56, h: 0.36, fontSize: 7 });
      text(slide, spec.title, { x: 1.09, y: 3.14, w: 10.19, h: 0.62, fontSize: 24 });
      slide.addShape("line", {
        x: 1.08,
        y: 3.81,
        w: 0.29,
        h: 0,
        line: { color: ACCENT, width: 1 },
      });
      text(slide, spec.subtitle, {
        x: 1.09,
        y: 3.87,
        w: 7.64,
        h: 0.37,
        fontSize: 10,
        color: ACCENT,
      });
      slide.addImage({ data: brand.script, x: 8.79, y: 5.03, w: 4.37, h: 2.21 });
    } else if (spec.kind === "chart") {
      content(slide, spec.title, spec.finding);
      master(slide, brand, page, true);
      text(slide, spec.spec.join("\n"), {
        x: 7.75,
        y: 0.42,
        w: 4.4,
        h: 0.95,
        fontSize: 11,
        valign: "top",
        fit: "shrink",
      });
      const pngs = await Promise.all(spec.charts.map(pngFor));
      // Two charts (bands + CF) share the bed; CF gets the narrow part.
      const shares = pngs.length > 1 ? [0.76, 0.24] : [1];
      let x = BED.x;
      pngs.forEach((png, i) => {
        const note = spec.charts[i].note;
        const w = BED.w * shares[i] - (pngs.length > 1 ? 0.1 : 0);
        const at = fit(png, { x, y: BED.y, w, h: BED.h - (note ? 0.25 : 0) });
        slide.addImage({ data: png.data, ...at });
        if (note)
          text(slide, note, { x, y: at.y + at.h + 0.02, w, h: 0.22, fontSize: 9, italic: true });
        x += BED.w * shares[i];
      });
    } else if (spec.kind === "relationships") {
      content(slide, spec.title, spec.lines.join("  "));
      master(slide, brand, page, true);
      if (spec.matrix.length) slide.addTable(rows(spec.matrix), table(0.41, 1.45, 7.6, 9));
      slide.addTable(rows(spec.strongest), table(8.25, 1.45, 4.7, 10));
    } else if (spec.kind === "observations") {
      summaryHead(slide, spec.title);
      master(slide, brand, page, false);
      slide.addTable(rows(spec.rows), table(0.43, 1.2, 11.84, 12, [1.11, 1.37, 3.01, 4.45, 1.9]));
    } else {
      summaryHead(slide, spec.title);
      master(slide, brand, page, false);
      const runs: PptxGenJS.TextProps[] = [];
      if (spec.nextSteps.length) {
        runs.push({ text: "Next step :", options: { fontSize: 24, breakLine: true } });
        spec.nextSteps.forEach((s, i) =>
          runs.push({ text: `${i + 1}. ${s}`, options: { fontSize: 12, breakLine: true } }),
        );
        runs.push({ text: " ", options: { fontSize: 12, breakLine: true } });
      }
      runs.push({ text: "Summary :", options: { fontSize: 18, breakLine: true } });
      for (const s of spec.summary)
        runs.push({ text: s, options: { fontSize: 12, breakLine: true } });
      slide.addText(runs, {
        x: 0.43,
        y: 1.25,
        w: 12.07,
        h: 5.5,
        fontFace: FONT,
        color: BLUE,
        valign: "top",
        margin: 0,
      });
    }
  }
  return pptx;
}

export async function exportReport(plan: SlideSpec[], fileName: string, pngFor: PngFor) {
  const deck = await buildDeck(plan, pngFor, await loadBrand());
  await deck.writeFile({ fileName });
}
