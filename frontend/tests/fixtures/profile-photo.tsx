// Development-only fixture: no measurements, API calls or writes.
import { createRoot } from "react-dom/client";
import { ProfilePhoto } from "../../src/features/measurements/monthly-detail/ProfilePhoto";
import "../../src/styles.css";
import "../../src/features/measurements/monthly-detail/monthly-detail.css";
const models = [
  "P703 DBL RANGER",
  "P703 DBL RAPTOR",
  "P703 DBL SUPER DUTY",
  "U704",
  "V363",
  "J73 DBL",
  "CX743",
];
const query = new URLSearchParams(location.search);
createRoot(document.getElementById("root")!).render(
  <main style={{ padding: 16 }}>
    <h1>Body colour preview verification</h1>
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,380px),1fr))",
        gap: 16,
      }}
    >
      {models.map((model) => (
        <section key={model}>
          <h2>{model}</h2>
          <ProfilePhoto
            model={model}
            hex={query.get("original") ? null : (query.get("hex") ?? "#175DC4")}
            colorName="Preview blue"
          />
        </section>
      ))}
    </div>
  </main>,
);
