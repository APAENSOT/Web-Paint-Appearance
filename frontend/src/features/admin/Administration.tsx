import { useQuery } from "@tanstack/react-query";
import { catalogueOptions, meOptions } from "@/api/queries";
import { isAdmin } from "@/api/roles";
import { AccessDenied } from "@/features/shell/AccessDenied";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { WorkspaceHeading } from "@/features/shell/VisualPlaceholder";
import { ColorFamilyAccordion } from "@/features/admin/ColorFamilyAccordion";
import { ModelAccordion } from "@/features/admin/ModelAccordion";

export function Administration() {
  const identity = useQuery(meOptions);
  if (identity.isPending) return <LoadingState>Loading session...</LoadingState>;
  if (identity.isError)
    return <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />;
  if (!isAdmin(identity.data.principal)) return <AccessDenied requiredRole="Admin" />;
  return <AdminCatalogue />;
}

function AdminCatalogue() {
  const catalogue = useQuery(catalogueOptions);
  if (catalogue.isPending) return <LoadingState>Loading catalogue...</LoadingState>;
  if (catalogue.isError)
    return <ApiErrorState error={catalogue.error} retry={() => void catalogue.refetch()} />;
  return (
    <section className="space-y-3">
      <WorkspaceHeading
        title="Administration"
        description="Plant-scoped colour families and offered model lists. Product pass-rate stays unavailable."
      />
      <div className="space-y-4">
        <ColorFamilyAccordion catalogue={catalogue.data} />
        <ModelAccordion catalogue={catalogue.data} />
      </div>
    </section>
  );
}
