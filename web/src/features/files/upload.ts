import { api, newIdempotencyKey, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type Attachment = components["schemas"]["Attachment"];

export const ACCEPTED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/webp"] as const;
type AcceptedType = (typeof ACCEPTED_TYPES)[number];
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

export type UploadStage = "sending" | "checking";

/** A message for the user, or null when the file can be uploaded. */
export function checkFile(file: File): string | null {
  if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) {
    return "Choose a PDF or a photo (JPEG, PNG or WebP).";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return "Files can be at most 20 MB.";
  return null;
}

const wait = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

/**
 * Upload straight to storage (docs/02-api-design.md §7): start (a presigned
 * PUT for exactly this type and size), PUT the bytes, complete, then wait
 * for the virus check. Resolves with the attachment once it is AVAILABLE.
 */
export async function uploadFile(
  file: File,
  onStage: (stage: UploadStage) => void = () => undefined,
  { pollMs = 1000, timeoutMs = 60_000 } = {},
): Promise<Attachment> {
  onStage("sending");
  const started = unwrap(
    await api.POST("/api/v1/attachments", {
      body: { filename: file.name, content_type: file.type as AcceptedType, size_bytes: file.size },
      headers: { "Idempotency-Key": newIdempotencyKey() },
    }),
  );
  // Straight to storage: no Authorization header, the URL itself is the permission.
  const put = await fetch(started.upload_url, {
    method: "PUT",
    headers: started.upload_headers,
    body: file,
  });
  if (!put.ok) throw new Error("The upload did not go through. Try again.");

  onStage("checking");
  const path = { attachment_id: started.attachment.id };
  unwrap(await api.POST("/api/v1/attachments/{attachment_id}/complete", { params: { path } }));
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const attachment = unwrap(
      await api.GET("/api/v1/attachments/{attachment_id}", { params: { path } }),
    );
    if (attachment.status === "AVAILABLE") return attachment;
    if (attachment.status === "QUARANTINED") {
      throw new Error("The file was rejected by the virus check.");
    }
    if (Date.now() > deadline) {
      throw new Error("The file is still being checked. Try again in a minute.");
    }
    await wait(pollMs);
  }
}
