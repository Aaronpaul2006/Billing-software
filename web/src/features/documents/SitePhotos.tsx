import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { LoadMore } from "@/components/LoadMore";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { PhotoGrid } from "@/features/files/PhotoGrid";
import { formatDate } from "@/lib/dates";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

/** Pick photos from the project's site diary, newest day first. */
function Chooser({
  documentId,
  projectId,
  chosen,
  onDone,
}: {
  documentId: string;
  projectId: string;
  chosen: string[];
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<string[]>(chosen);
  const days = useInfiniteQuery({
    queryKey: ["diary", projectId],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/diary", {
          params: {
            path: { project_id: projectId },
            query: { limit: 20, ...(pageParam ? { cursor: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/documents/{document_id}/photos", {
          params: { path: { document_id: documentId } },
          body: { diary_photo_ids: picked },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(["document-photos", documentId], saved);
      onDone();
    },
  });
  const entries = (days.data?.pages.flatMap((p) => p.results) ?? []).filter(
    (e) => e.photos.length > 0,
  );
  return (
    <div className="grid gap-4">
      {save.error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{save.error.message}</AlertDescription>
        </Alert>
      )}
      {days.isSuccess && entries.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No photos in this project&apos;s{" "}
          <Link to={`/projects/${projectId}/diary`} className="underline">
            site diary
          </Link>{" "}
          yet.
        </p>
      )}
      {entries.map((e) => (
        <section key={e.id} aria-label={formatDate(e.entry_date)} className="grid gap-2">
          <h3 className="text-sm font-medium">{formatDate(e.entry_date)}</h3>
          <ul className="grid grid-cols-3 gap-2">
            {e.photos.map((p) => {
              const on = picked.includes(p.id);
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    aria-pressed={on}
                    aria-label={p.caption || `Photo, ${formatDate(e.entry_date)}`}
                    className={cn(
                      "relative block w-full overflow-hidden rounded-md border-2",
                      on ? "border-primary" : "border-transparent",
                    )}
                    onClick={() => {
                      setPicked((now) => (on ? now.filter((x) => x !== p.id) : [...now, p.id]));
                    }}
                  >
                    <img
                      src={p.url}
                      alt=""
                      loading="lazy"
                      className="bg-muted aspect-[4/3] w-full object-cover"
                    />
                    {on && (
                      <span className="bg-primary text-primary-foreground absolute top-1 right-1 rounded-full p-0.5">
                        <Check className="size-3.5" aria-hidden />
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <LoadMore query={days} />
      <div className="bg-background sticky bottom-0 flex gap-2 border-t pt-3">
        <Button
          disabled={save.isPending}
          onClick={() => {
            save.mutate();
          }}
        >
          Show {picked.length} {picked.length === 1 ? "photo" : "photos"} with the bill
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** Proof of work: site diary photos shown with the bill (and in the client portal). */
export function SitePhotos({
  documentId,
  projectId,
  cancelled,
}: {
  documentId: string;
  projectId: string | null;
  cancelled: boolean;
}) {
  const { role } = useSession();
  const [choosing, setChoosing] = useState(false);
  const photos = useQuery({
    queryKey: ["document-photos", documentId],
    enabled: projectId !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}/photos", {
          params: { path: { document_id: documentId } },
        }),
      ),
  });
  if (projectId === null) return null;
  const chosen = photos.data?.results ?? [];
  const mayChoose = can(role, "documents.draft") && !cancelled;
  if (chosen.length === 0 && !mayChoose) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Site photos</h2>
        </CardTitle>
        <CardDescription>
          Proof of work from the site diary. The client sees them with the bill in the portal.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {chosen.length > 0 && <PhotoGrid photos={chosen} label="Site photos with this bill" />}
        {mayChoose && (
          <Button
            variant="outline"
            className="justify-self-start"
            onClick={() => {
              setChoosing(true);
            }}
          >
            {chosen.length ? "Change the photos…" : "Choose site photos…"}
          </Button>
        )}
      </CardContent>
      <Sheet open={choosing} onOpenChange={setChoosing}>
        <SheetContent
          side="right"
          closeLabel="Close"
          className="w-full max-w-lg overflow-y-auto p-4 pt-12 sm:w-[32rem] sm:max-w-lg"
        >
          <SheetTitle className="text-section">Choose site photos</SheetTitle>
          <SheetDescription className="text-muted-foreground text-sm">
            Tap the photos to show with this bill, in the order you tap them.
          </SheetDescription>
          {choosing && (
            <Chooser
              documentId={documentId}
              projectId={projectId}
              chosen={chosen.map((p) => p.id)}
              onDone={() => {
                setChoosing(false);
              }}
            />
          )}
        </SheetContent>
      </Sheet>
    </Card>
  );
}
