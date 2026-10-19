// Local asset capture only. Reads the same registered body; never calls the API.
import { createStudio } from "../model-studio/scene";
import { PREPARED_BODIES } from "../model-studio/body-assets";
const model = new URLSearchParams(location.search).get("model") ?? "CX743";
const asset = PREPARED_BODIES[model];
const stage = document.getElementById("thumbnail") as HTMLDivElement;
if (!asset) throw new Error("Use an exact prepared model code.");
const studio = createStudio(
  stage,
  (state) => {
    stage.setAttribute("aria-label", state.ready ? "Framing body thumbnail" : state.status);
    if (state.ready) {
      studio.motion(false);
      studio.view("body");
      requestAnimationFrame(() =>
        requestAnimationFrame(() =>
          stage.setAttribute("aria-label", `Ready ${model} body thumbnail`),
        ),
      );
    }
  },
  asset,
);
studio.motion(false);
studio.view("body");
window.addEventListener("pagehide", () => studio.dispose(), { once: true });
