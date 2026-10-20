import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/problem";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 4xx answers will not change on retry (403, 404, 422...).
        retry: (count, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
        refetchOnWindowFocus: false,
      },
    },
  });
}
