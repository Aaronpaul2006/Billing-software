import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

/** The signed-in user and their companies. */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me")),
    staleTime: 5 * 60_000,
  });
}
