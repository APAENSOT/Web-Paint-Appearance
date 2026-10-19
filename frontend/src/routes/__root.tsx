import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { Link, Outlet, createRootRouteWithContext } from "@tanstack/react-router";

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: RootComponent,
  notFoundComponent: () => (
    <div className="panel m-6 p-8">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block text-primary">
        Return to Overview
      </Link>
    </div>
  ),
  errorComponent: ({ reset }) => (
    <div role="alert" className="panel m-6 p-8">
      <h1 className="text-xl font-semibold">This page could not load</h1>
      <button className="mt-4 text-primary" onClick={reset}>
        Try again
      </button>
    </div>
  ),
});

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  return (
    <QueryClientProvider client={queryClient}>
      <Outlet />
    </QueryClientProvider>
  );
}
