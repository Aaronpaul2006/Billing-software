import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type PrintSettings = components["schemas"]["PrintSettings"];

export const PRINT_SETTINGS_KEY = ["tenant", "print-settings"] as const;

/** Logo, bank details, UPI ID, default terms and layout (B.12); every member may read them. */
export function usePrintSettings() {
  return useQuery({
    queryKey: PRINT_SETTINGS_KEY,
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant/print-settings")),
    staleTime: 5 * 60_000,
  });
}

/** Same limits as the server: PNG or JPEG, at most 1 MB (every PDF carries them). */
export const IMAGE_TYPES = ["image/png", "image/jpeg"];
const MAX_IMAGE_BYTES = 1024 * 1024;

/** A message for the user, or null when the image can be uploaded. */
export function checkImage(file: File): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return "Choose a PNG or JPEG image.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_IMAGE_BYTES) return "The image can be at most 1 MB.";
  return null;
}
