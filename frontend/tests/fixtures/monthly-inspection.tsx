// Development fixture only. All sample values supplied by the browser test.
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProfileInspection } from "../../src/features/measurements/monthly-detail/ProfileInspection";
import "../../src/styles.css";
import "../../src/features/measurements/monthly-detail/monthly-detail.css";
const domain = new URLSearchParams(location.search).get("domain") === "film" ? "film" : "wavescan";
const client = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <main style={{ padding: 16 }}>
      <p>Interaction fixture · synthetic readings · no writes</p>
      <ProfileInspection
        plant="FTM"
        month="2026-09"
        profile={{
          profile_id: "fixture",
          model_code: "P703 DBL RANGER",
          color_name: "Arctic White",
          family_name: "Light Solids",
          domain,
          is_offered: true,
          sample_count: 3,
        }}
        hex="#203040"
        onBack={() => {}}
      />
    </main>
  </QueryClientProvider>,
);
