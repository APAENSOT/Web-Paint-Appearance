import { createFileRoute } from "@tanstack/react-router";
import { Intake } from "@/features/intake/Intake";
import { ParkedChrome } from "@/features/shell/ParkedChrome";

export const Route = createFileRoute("/batches")({
  component: () => (
    <ParkedChrome>
      <Intake />
    </ParkedChrome>
  ),
});
