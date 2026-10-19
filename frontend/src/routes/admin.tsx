import { createFileRoute } from "@tanstack/react-router";
import { Administration } from "@/features/admin/Administration";
import { ParkedChrome } from "@/features/shell/ParkedChrome";

export const Route = createFileRoute("/admin")({
  component: () => (
    <ParkedChrome>
      <Administration />
    </ParkedChrome>
  ),
});
