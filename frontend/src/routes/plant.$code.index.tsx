import { createFileRoute } from "@tanstack/react-router";
import { PlantMeasurements } from "@/features/measurements/PlantMeasurements";
import { PointLabelsProvider } from "@/features/measurements/point-labels";

export const Route = createFileRoute("/plant/$code/")({ component: PlantRoute });

function PlantRoute() {
  const { code } = Route.useParams();
  // RO17 (D-RO17-16): the plant's own point words for every box summary below.
  return (
    <PointLabelsProvider plant={code}>
      <PlantMeasurements key={code} code={code} />
    </PointLabelsProvider>
  );
}
