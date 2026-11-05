import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, BookmarkPlus, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useSession } from "@/auth/context";
import { Field } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/errors";
import { can } from "@/lib/permissions";

import { TEMPLATE_TYPES } from "./templates";

/** "Save as template" on a quote or bill: its lines, notes and terms under a name. */
export function SaveAsTemplate({ documentId, docType }: { documentId: string; docType: string }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [days, setDays] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/save-as-template", {
          params: { path: { document_id: documentId } },
          body: { name: name.trim(), valid_days: days ? Number(days) : null },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      setKey(newIdempotencyKey());
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  if (!TEMPLATE_TYPES.has(docType) || !can(session.role, "masters.edit")) return null;
  const quotation = docType === "QUOTATION";
  return (
    <div className="grid gap-2">
      {save.isSuccess && !open && (
        <Alert>
          <CheckCircle2 aria-hidden />
          <AlertDescription>
            Saved as the template “{save.data.name}”.{" "}
            <Link to="/templates" className="underline">
              See templates
            </Link>
          </AlertDescription>
        </Alert>
      )}
      {!open ? (
        <div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setOpen(true);
              save.reset();
            }}
          >
            <BookmarkPlus aria-hidden /> Save as template
          </Button>
        </div>
      ) : (
        <form
          aria-label="Save as template"
          className="bg-muted/40 grid max-w-xl gap-3 rounded-lg border p-3 sm:grid-cols-[1fr_8rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) save.mutate();
          }}
        >
          <Field id="template-name" label="Template name">
            <Input
              id="template-name"
              value={name}
              maxLength={100}
              placeholder="e.g. 2BHK interior package"
              onChange={(e) => {
                setName(e.target.value);
              }}
            />
          </Field>
          {quotation ? (
            <Field id="template-days" label="Valid for (days)">
              <Input
                id="template-days"
                inputMode="numeric"
                value={days}
                placeholder="as this quote"
                onChange={(e) => {
                  setDays(e.target.value.replace(/\D/g, "").slice(0, 3));
                }}
              />
            </Field>
          ) : (
            <div />
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={!name.trim() || save.isPending}>
              Save
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setOpen(false);
              }}
            >
              Cancel
            </Button>
          </div>
          {save.error && (
            <Alert variant="destructive" className="sm:col-span-3">
              <AlertCircle aria-hidden />
              <AlertDescription>
                {save.error instanceof ApiError && save.error.code === "template_name_taken"
                  ? "A template with this name already exists: choose another name."
                  : errorMessage(save.error)}
              </AlertDescription>
            </Alert>
          )}
        </form>
      )}
    </div>
  );
}
