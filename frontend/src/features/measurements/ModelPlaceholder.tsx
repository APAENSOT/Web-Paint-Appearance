import { Link } from "@tanstack/react-router";
import { VisualPlaceholder, WorkspaceHeading } from "@/features/shell/VisualPlaceholder";

export function ModelPlaceholder({ code }: { code: string }) {
  return (
    <section className="space-y-3">
      <WorkspaceHeading title="Model Detail" description={`${code} plant workspace`} />
      <VisualPlaceholder
        title="Model view reserved"
        reason="Model detail is unavailable in this phase. This route remains unused in the walkthrough."
      >
        <Link
          to="/plant/$code"
          params={{ code }}
          className="mt-3 text-sm font-medium text-primary underline underline-offset-4"
        >
          Back to plant workspace
        </Link>
      </VisualPlaceholder>
    </section>
  );
}
