import { createFileRoute } from "@tanstack/react-router";
import { Analysis } from "@/features/analysis/Analysis";
import { ParkedChrome } from "@/features/shell/ParkedChrome";

export const Route = createFileRoute("/analysis")({
  component: () => (
    <ParkedChrome>
      <Analysis />
    </ParkedChrome>
  ),
});
