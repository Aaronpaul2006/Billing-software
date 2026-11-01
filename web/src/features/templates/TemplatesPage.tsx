import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useSession } from "@/auth/context";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/PartyPicker";
import type { PickedParty } from "@/components/PartyPicker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { isoDate } from "@/features/dashboard/periods";
import { DOC_TYPE_LABELS } from "@/features/documents/api";
import type { DocType } from "@/features/documents/api";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";

import { CAN_EDIT, CAN_USE } from "./templates";
import type { Template } from "./templates";

function problemText(e: unknown): string {
  if (e instanceof ApiError && e.code === "template_name_taken") {
    return "A template with this name already exists.";
  }
  if (e instanceof ApiError && e.problem.errors?.length) {
    return e.problem.errors.map((x) => x.message).join(" ");
  }
  return errorMessage(e);
}

/** Choose the client (and project, date) and open the new draft in the editor. */
function UseTemplate({ template, onClose }: { template: Template; onClose: () => void }) {
  const navigate = useNavigate();
  const [party, setParty] = useState<PickedParty | null>(null);
  const [projectId, setProjectId] = useState("");
  const [date, setDate] = useState(() => isoDate(new Date()));
  const [key] = useState(newIdempotencyKey);
  const projects = useQuery({
    queryKey: ["projects", "of", party?.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects", {
          params: { query: { client_party_id: party?.id ?? "", limit: 100, ordering: "code" } },
        }),
      ).results,
    enabled: party !== null,
  });
  const use = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/document-templates/{template_id}/use", {
          params: { path: { template_id: template.id } },
          body: { party_id: party?.id ?? "", project_id: projectId || null, doc_date: date },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (draft) => {
      void navigate(`/documents/${draft.id}/edit`);
    },
  });
  return (
    <form
      aria-label={`Use ${template.name}`}
      className="bg-muted/40 grid gap-3 rounded-lg border p-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (party) use.mutate();
      }}
    >
      <Field id={`use-${template.id}-client`} label="Client">
        <PartyPicker
          id={`use-${template.id}-client`}
          value={party}
          onChange={(p) => {
            setParty(p);
            setProjectId("");
          }}
        />
      </Field>
      <Field id={`use-${template.id}-project`} label="Project">
        <NativeSelect
          id={`use-${template.id}-project`}
          value={projectId}
          disabled={!party}
          onChange={(e) => {
            setProjectId(e.target.value);
          }}
        >
          <option value="">No project</option>
          {projects.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} · {p.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id={`use-${template.id}-date`} label="Date">
        <Input
          id={`use-${template.id}-date`}
          type="date"
          value={date}
          onChange={(e) => {
            setDate(e.target.value);
          }}
        />
      </Field>
      {use.error && (
        <Alert variant="destructive" className="sm:col-span-3">
          <AlertCircle aria-hidden />
          <AlertDescription>{problemText(use.error)}</AlertDescription>
        </Alert>
      )}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" disabled={!party || use.isPending}>
          Create the draft
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Rename({ template, onClose }: { template: Template; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(template.name);
  const rename = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/document-templates/{template_id}", {
          params: { path: { template_id: template.id } },
          body: { name: name.trim() },
          headers: { "If-Match": ifMatch(template.version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
      onClose();
    },
  });
  return (
    <form
      aria-label={`Rename ${template.name}`}
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) rename.mutate();
      }}
    >
      <Field id={`rename-${template.id}`} label="New name">
        <Input
          id={`rename-${template.id}`}
          value={name}
          maxLength={100}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
      </Field>
      <Button type="submit" size="sm" disabled={!name.trim() || rename.isPending}>
        Save
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onClose}>
        Cancel
      </Button>
      {rename.error && (
        <p className="text-destructive w-full text-sm">{problemText(rename.error)}</p>
      )}
    </form>
  );
}

/** Saved quotes and bills to start new drafts from. */
export function TemplatesPage() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<{ id: string; kind: "use" | "rename" } | null>(null);
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/document-templates", {
          params: { query: { ordering: "name", limit: 100 } },
        }),
      ).results,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/document-templates/{template_id}", {
          params: { path: { template_id: id } },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  const canEdit = CAN_EDIT.has(session.role);
  const canUse = CAN_USE.has(session.role);
  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/documents">
          <ArrowLeft aria-hidden /> Invoices & quotes
        </Link>
      </Button>
      <PageHeader
        title="Templates"
        description="Standard quotes and bills. Save one from any quote or invoice (“Save as template”), then start new drafts from it."
      />
      {remove.error && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle aria-hidden />
          <AlertDescription>{problemText(remove.error)}</AlertDescription>
        </Alert>
      )}
      {templates.error ? (
        <ErrorState error={templates.error} />
      ) : !templates.data ? (
        <Skeleton className="h-24 w-full" />
      ) : templates.data.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No templates yet. Open a quote or invoice and choose “Save as template”.
        </p>
      ) : (
        <ul className="grid max-w-4xl gap-3">
          {templates.data.map((t) => (
            <li key={t.id} className="rounded-lg border p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-48 flex-1">
                  <div className="font-medium">{t.name}</div>
                  <div className="text-muted-foreground text-sm">
                    {DOC_TYPE_LABELS[t.doc_type as DocType]} · {t.lines.length}{" "}
                    {t.lines.length === 1 ? "line" : "lines"}
                    {t.valid_days ? ` · valid ${String(t.valid_days)} days` : ""}
                  </div>
                </div>
                {canUse && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setPanel({ id: t.id, kind: "use" });
                    }}
                  >
                    Use
                  </Button>
                )}
                {canEdit && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setPanel({ id: t.id, kind: "rename" });
                      }}
                    >
                      Rename
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Delete ${t.name}`}
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm(`Delete the template “${t.name}”?`)) remove.mutate(t.id);
                      }}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </>
                )}
              </div>
              {panel?.id === t.id && (
                <div className="mt-3">
                  {panel.kind === "use" ? (
                    <UseTemplate
                      template={t}
                      onClose={() => {
                        setPanel(null);
                      }}
                    />
                  ) : (
                    <Rename
                      template={t}
                      onClose={() => {
                        setPanel(null);
                      }}
                    />
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
