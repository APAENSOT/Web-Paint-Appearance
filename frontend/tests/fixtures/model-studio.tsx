// Standalone Vite development fixture. Never imported by production routes.
// Query cache contains labelled test data; viewer role prevents persistent writes.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router";
import { ModelStudio } from "../../src/features/measurements/model-studio/ModelStudio";
import {
  ModelStudioNav,
  type StudioMode,
} from "../../src/features/measurements/model-studio/ModelStudioNav";
import { SettingsPanel } from "../../src/components/ct/SettingsPanel";
import { RANGER_MODEL } from "../../src/features/measurements/model-studio/catalogue";
import "../../src/styles.css";

const client = new QueryClient({
  defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnWindowFocus: false } },
});
client.setQueryData(["identity"], { principal: { roles: ["viewer"] } });
client.setQueryData(["standards", "model-points", "FTM"], {
  models: [{ model_code: RANGER_MODEL, display_name: "Ranger" }],
});
client.setQueryData(["color-appearances", "FTM"], {
  items: [
    {
      color_name: "Test blue",
      color_group: "Fixture",
      appearance: { hex: "#376A94", revision: 1 },
    },
    {
      color_name: "Test white",
      color_group: "Fixture",
      appearance: { hex: "#DDDFDE", revision: 1 },
    },
  ],
});
client.setQueryData(["ws-points", "FTM", RANGER_MODEL], {
  items: Array.from({ length: 32 }, (_, i) => ({
    zone_code: `Test point ${i + 1}`,
    point_no: i + 1,
    counted: true,
  })),
});
client.setQueryData(["filmthickness", "points", "FTM", RANGER_MODEL], {
  items: Array.from({ length: 98 }, (_, i) => ({
    point_code: `Test film ${i + 1}`,
    point_no: i + 1,
    counted: true,
  })),
});

function Fixture() {
  const [mode, setMode] = useState<StudioMode>("points");
  const [locked, setLocked] = useState(false);
  return (
    <QueryClientProvider client={client}>
      <div style={{ padding: 16 }}>
        <p style={{ marginBottom: 16 }}>Interaction test · Fixture data only · No storage writes</p>
        <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
          <SettingsPanel
            active="model"
            onSelect={() => {}}
            modelChildren={
              <ModelStudioNav
                mode={mode === "points" ? "inspection" : "colours"}
                disabled={locked}
                canEditPoints={false}
                onSelect={(next) => {
                  if (next === "colours" || next === "inspection")
                    setMode(next === "inspection" ? "points" : "colours");
                }}
              />
            }
          />
          <div style={{ flex: "1 1 700px", minWidth: 0 }}>
            <ModelStudio code="FTM" mode={mode} onModeLockChange={setLocked} />
          </div>
        </div>
      </div>
    </QueryClientProvider>
  );
}
const root = createRootRoute({ component: Fixture });
const router = createRouter({ routeTree: root });
createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);
