import { Outlet, createFileRoute } from "@tanstack/react-router";
import { parsePlantSearch } from "@/features/measurements/history-search";
export const Route = createFileRoute("/plant/$code")({
  validateSearch: parsePlantSearch,
  component: () => <Outlet />,
});
