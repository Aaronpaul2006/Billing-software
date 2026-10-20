import { queryOptions, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./client";

export const meQuery = queryOptions({
  queryKey: ["me"],
  queryFn: async () => unwrap(await api.GET("/api/v1/me")),
  staleTime: 5 * 60_000,
});

/** The signed-in user and their companies. */
export function useMe() {
  return useQuery(meQuery);
}
