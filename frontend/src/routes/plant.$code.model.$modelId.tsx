import { createFileRoute } from "@tanstack/react-router";
import { ColourDashboard } from "@/features/measurements/ColourDashboard";

export const Route = createFileRoute("/plant/$code/model/$modelId")({ component: ModelDetail });

function ModelDetail() {
  const { code, modelId } = Route.useParams();
  return <ColourDashboard code={code} modelId={modelId} />;
}
