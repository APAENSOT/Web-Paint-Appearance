import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { meOptions, metaOptions } from "@/api/queries";
import { mayIngest, mayManagePlantFiles } from "@/api/roles";
import { AccessDenied } from "@/features/shell/AccessDenied";
import { ApiErrorState, LoadingState } from "@/components/ApiState";

export function Intake() {
  const identity = useQuery(meOptions);
  if (identity.isPending) return <LoadingState>Loading session...</LoadingState>;
  if (identity.isError)
    return <ApiErrorState error={identity.error} retry={() => void identity.refetch()} />;
  if (!mayIngest(identity.data.principal)) return <AccessDenied requiredRole="Engineer" />;
  if (!mayManagePlantFiles(identity.data.principal))
    return (
      <section className="panel p-6">
        <p className="eyebrow">Plant Data</p>
        <h1 className="mt-2 text-xl font-semibold">Plant uploads are Admin-only</h1>
        <p className="my-3 text-sm text-muted-foreground">
          Upload is available to Admin on plant Upload Data this phase. Open a plant's Measurement
          History to inspect active data and use Correct.
        </p>
        <Link
          to="/plant/$code"
          params={{ code: "ftm" }}
          search={{ dataView: "history" }}
          className="text-primary underline"
        >
          Open FTM Measurement History
        </Link>
      </section>
    );
  return <PlantChooser />;
}

function PlantChooser() {
  const metadata = useQuery(metaOptions);
  return (
    <section className="panel p-5">
      <p className="eyebrow">Plant Data / Upload Data</p>
      <h1 className="mt-2 text-xl font-semibold">Choose a plant</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Open plant Upload Data to upload and review workbooks in that plant's scope.
      </p>
      {metadata.isPending ? (
        <LoadingState>Loading plants...</LoadingState>
      ) : metadata.isError ? (
        <ApiErrorState error={metadata.error} retry={() => void metadata.refetch()} />
      ) : (
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {metadata.data.plants.map((plant) => (
            <Link
              key={plant.plant_code}
              to="/plant/$code"
              params={{ code: plant.plant_code.toLowerCase() }}
              search={{ dataView: "upload" }}
              className="rounded-sm border border-border p-5 hover:bg-muted/30"
            >
              <h2 className="font-semibold">
                {plant.plant_code} / {plant.plant_name}
              </h2>
              <p className="mt-2 text-xs text-muted-foreground">
                {plant.is_active ? "Open Upload Data" : "Not onboarded - plant remains visible"}
              </p>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
