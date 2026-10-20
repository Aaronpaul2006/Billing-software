import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, X } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

import { ACCEPTED_TYPES, checkFile, uploadFile } from "./upload";
import type { UploadStage } from "./upload";

const STAGE_TEXT: Record<UploadStage, string> = {
  sending: "Uploading…",
  checking: "Checking the file…",
};

/**
 * One file (a bill, a receipt, a site photo): upload, view, remove. `value` is
 * the attachment id; only files that passed the checks are ever set.
 */
export function AttachmentField({
  id,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  value: string | null;
  onChange: (attachmentId: string | null) => void;
  disabled?: boolean;
}) {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<UploadStage | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const current = useQuery({
    queryKey: ["attachment", value],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/attachments/{attachment_id}", {
          params: { path: { attachment_id: value ?? "" } },
        }),
      ),
    enabled: value !== null,
    staleTime: 4 * 60_000, // the download link lasts 5 minutes
  });
  const upload = useMutation({
    mutationFn: (file: File) => uploadFile(file, setStage),
    onSuccess: (attachment) => {
      queryClient.setQueryData(["attachment", attachment.id], attachment);
      onChange(attachment.id);
    },
    onError: (e) => {
      setProblem(e instanceof ApiError ? errorMessage(e) : e.message);
    },
    onSettled: () => {
      setStage(null);
    },
  });

  if (value !== null) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <FileText className="size-4" aria-hidden />
        {current.data?.download_url ? (
          <a
            href={current.data.download_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            {current.data.filename}
          </a>
        ) : (
          <span>{current.data?.filename ?? "Attached file"}</span>
        )}
        {!disabled && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Remove the file"
            onClick={() => {
              onChange(null);
            }}
          >
            <X aria-hidden />
          </Button>
        )}
      </div>
    );
  }
  return (
    <div className="grid gap-1 text-sm">
      {stage ? (
        <p role="status" className="text-muted-foreground flex items-center gap-2">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          {STAGE_TEXT[stage]}
        </p>
      ) : (
        <input
          id={id}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          disabled={disabled}
          className="text-sm file:mr-3 file:rounded-md file:border file:px-3 file:py-1"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // choosing the same file again still fires
            if (!file) return;
            const reason = checkFile(file);
            setProblem(reason);
            if (!reason) upload.mutate(file);
          }}
        />
      )}
      {problem && <p className="text-destructive">{problem}</p>}
    </div>
  );
}
