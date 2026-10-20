import { QueryClientProvider } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import { AuthProvider } from "@/auth/AuthProvider";
import { makeQueryClient } from "@/queryClient";
import { routes } from "@/routes";

/** Query cache and auth, around any router (the app, or a memory router in tests). */
export function Providers({
  queryClient,
  children,
}: {
  queryClient: QueryClient;
  children: ReactNode;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

export function App() {
  const [router] = useState(() => createBrowserRouter(routes));
  const [queryClient] = useState(makeQueryClient);
  return (
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  );
}
