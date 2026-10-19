/* Transport mode lens — kept in its own module so state providers never
   import the heavy map component (which breaks React context on HMR). */
export type Mode = "ocean" | "air" | "rail" | "road";
export const MODES: Mode[] = ["ocean", "air", "rail", "road"];
