// UI colour conversions only. No relationship to paint formulae or grading.
export type RGB = [number, number, number];
export type HSV = { h: number; s: number; v: number };
export const NEUTRAL_BODY = "#D6DCDF";

export function parseHex(value: string): string | null {
  const hex = value.trim().replace(/^#/, "");
  if (/^[\da-f]{3}$/i.test(hex))
    return `#${[...hex]
      .map((c) => c + c)
      .join("")
      .toUpperCase()}`;
  return /^[\da-f]{6}$/i.test(hex) ? `#${hex.toUpperCase()}` : null;
}

export function parseChannel(value: string): number | null {
  if (!/^\d{1,3}$/.test(value)) return null;
  const channel = Number(value);
  return channel <= 255 ? channel : null;
}

export function hexToRgb(hex: string): RGB {
  return [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16)) as RGB;
}

export function rgbToHex(rgb: RGB): string {
  return `#${rgb
    .map((c) => c.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;
}

export function rgbToHsv(rgb: RGB): HSV {
  const [r, g, b] = rgb.map((channel) => channel / 255);
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    delta = max - min;
  let h = 0;
  if (delta) {
    h = max === r ? ((g - b) / delta) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
    h = (h * 60 + 360) % 360;
  }
  return { h, s: max === 0 ? 0 : delta / max, v: max };
}

export function hsvToRgb({ h, s, v }: HSV): RGB {
  const channel = (n: number) => {
    const k = (n + h / 60) % 6;
    return Math.round(255 * (v - v * s * Math.max(0, Math.min(k, 4 - k, 1))));
  };
  return [channel(5), channel(3), channel(1)];
}

export function wheelPosition(x: number, y: number): Pick<HSV, "h" | "s"> {
  return { h: ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360, s: Math.min(1, Math.hypot(x, y)) };
}
