import { VisualPlaceholder, WorkspaceHeading } from "@/features/shell/VisualPlaceholder";

export function Analysis() {
  return (
    <section className="space-y-3">
      <WorkspaceHeading title="Analysis" description="WaveScan trends and reports." />
      <VisualPlaceholder
        title="Trends & distributions"
        reason="Charts, filters and raw CF previews are parked for this visual walkthrough. Analysis will be connected in a later phase."
      />
    </section>
  );
}
