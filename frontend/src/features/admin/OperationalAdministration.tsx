import { useQuery } from "@tanstack/react-query";
import { meOptions, metaOptions } from "@/api/queries";
import { isAdmin, roleLabel } from "@/api/roles";
import { AccessDenied } from "@/features/shell/AccessDenied";
import { ApiErrorState, LoadingState } from "@/components/ApiState";
import { Button } from "@/components/ui/button";

export function OperationalAdministration() {
  const identity = useQuery(meOptions);
  if (identity.isPending) return <LoadingState>Loading session…</LoadingState>;
  if (identity.isError)
    return <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />;
  if (!isAdmin(identity.data.principal)) return <AccessDenied requiredRole="Admin" />;
  return <AdminStatus />;
}

function AdminStatus() {
  const identity = useQuery(meOptions);
  const meta = useQuery(metaOptions);
  const session = identity.data!;
  return (
    <section>
      <h1 className="text-3xl font-semibold tracking-tight">Administration</h1>
      <p className="mt-3 text-sm text-muted-foreground">
        Read-only platform status and the identity reported by the service.
      </p>
      <div className="mt-7 grid gap-5 xl:grid-cols-2">
        <section className="panel p-6">
          <h2 className="text-lg font-semibold">Current session</h2>
          <dl className="mt-5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-4 text-sm">
            {[
              ["Name", session.principal.display_name],
              ["Roles", roleLabel(session.principal)],
              ["Authentication", session.principal.auth_source],
              ["Environment", session.environment],
              [
                "Plant scope",
                session.plant_scope === null
                  ? "All plants (provisional policy)"
                  : session.plant_scope.join(", ") || "No plants",
              ],
              ["Scope note", session.plant_scope_note],
            ].map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="break-words">{value}</dd>
              </div>
            ))}
          </dl>
        </section>
        <section className="panel p-6">
          <h2 className="text-lg font-semibold">Reference data</h2>
          {meta.isPending ? (
            <LoadingState>Loading reference data…</LoadingState>
          ) : meta.isError ? (
            <ApiErrorState error={meta.error} retry={() => void meta.refetch()} />
          ) : (
            <>
              <p className="mt-5 text-sm text-muted-foreground">Unmapped colours</p>
              <p className="num mt-2 text-4xl font-semibold">{meta.data.unmapped_color_count}</p>
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                Colours awaiting grading-family mapping. This count does not assign a family.
              </p>
              <h3 className="mt-6 text-sm font-semibold">Plants</h3>
              <ul className="mt-3 space-y-2 text-sm">
                {meta.data.plants.map((plant) => (
                  <li key={plant.plant_code}>
                    <span className="font-medium">{plant.plant_code}</span> · {plant.plant_name}
                  </li>
                ))}
              </ul>
              <p className="mt-5 text-sm">
                Grading available: {String(meta.data.grading_available)}
              </p>
            </>
          )}
        </section>
      </div>
      <section className="panel mt-5 p-6">
        <h2 className="text-lg font-semibold">Grading unavailable</h2>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Grouping and colour-family mapping remain unresolved. Standards publishing is reserved
          until colour-family mapping is approved.
        </p>
        <Button className="mt-5" variant="outline" disabled>
          Standards publishing · Reserved
        </Button>
      </section>
    </section>
  );
}
