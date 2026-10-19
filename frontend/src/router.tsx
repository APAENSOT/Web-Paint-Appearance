import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient({
    // 30 s: moving between sections reuses what was just read instead of
    // refetching it; every write still invalidates its own queries at once.
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 30_000 } },
  });
  return createRouter({ routeTree, context: { queryClient }, scrollRestoration: true });
};
