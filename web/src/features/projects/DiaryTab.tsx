import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Camera, CloudRain, Cloud, Sun, Trash2, Users } from "lucide-react";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { Field } from "@/components/FormField";
import { LoadMore } from "@/components/LoadMore";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { isoDate } from "@/features/dashboard/periods";
import { shrinkPhoto } from "@/features/files/shrink";
import { checkFile, uploadFile } from "@/features/files/upload";
import { formatDate } from "@/lib/dates";
import { ifMatch } from "@/lib/forms";
import { can } from "@/lib/permissions";

import { useProjectOutlet } from "./api";

type Entry = components["schemas"]["Entry"];
type Weather = NonNullable<Entry["weather"]>;

const WEATHER: Record<Weather, { label: string; icon: typeof Sun }> = {
  SUNNY: { label: "Sunny", icon: Sun },
  CLOUDY: { label: "Cloudy", icon: Cloud },
  RAIN: { label: "Rain", icon: CloudRain },
  HEAVY_RAIN: { label: "Heavy rain", icon: CloudRain },
};

const TEXTAREA =
  "border-input bg-background placeholder:text-muted-foreground focus-visible:ring-ring/50 focus-visible:border-ring min-h-24 w-full rounded-md border px-3 py-2 text-base shadow-xs outline-none focus-visible:ring-[3px] md:text-sm";

function problem(e: unknown): string {
  if (e instanceof ApiError && e.problem.errors?.length)
    return e.problem.errors.map((x) => x.message).join(" ");
  return e instanceof Error ? e.message : "Something went wrong.";
}

interface Picked {
  key: string;
  file: File;
  caption: string;
}

/** Photos from the camera or the gallery, made smaller, uploaded and checked. */
async function uploadPhotos(
  picked: Picked[],
  onProgress: (done: number) => void,
): Promise<{ attachment_id: string; caption: string }[]> {
  const out: { attachment_id: string; caption: string }[] = [];
  for (const p of picked) {
    const small = await shrinkPhoto(p.file);
    const bad = checkFile(small);
    if (bad) throw new Error(`${p.file.name}: ${bad}`);
    const attachment = await uploadFile(small);
    out.push({ attachment_id: attachment.id, caption: p.caption.trim() });
    onProgress(out.length);
  }
  return out;
}

function PhotoPicker({
  picked,
  onChange,
}: {
  picked: Picked[];
  onChange: (next: Picked[]) => void;
}) {
  return (
    <div className="grid gap-2">
      <label className="border-input hover:bg-accent flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-dashed px-3 text-sm">
        <Camera className="size-4" aria-hidden />
        Add photos
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          capture="environment"
          multiple
          className="sr-only"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            onChange([
              ...picked,
              ...files.map((file) => ({
                key: `${file.name}-${String(Math.random())}`,
                file,
                caption: "",
              })),
            ]);
            e.target.value = "";
          }}
        />
      </label>
      {picked.length > 0 && (
        <ul aria-label="Photos to add" className="grid gap-2">
          {picked.map((p, i) => (
            <li key={p.key} className="flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{p.file.name}</span>
              <Input
                aria-label={`Caption for photo ${String(i + 1)}`}
                placeholder="Caption (optional)"
                className="max-w-56"
                value={p.caption}
                onChange={(e) => {
                  onChange(
                    picked.map((x) => (x.key === p.key ? { ...x, caption: e.target.value } : x)),
                  );
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove photo ${String(i + 1)}`}
                onClick={() => {
                  onChange(picked.filter((x) => x.key !== p.key));
                }}
              >
                <Trash2 aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Write a day, or change one (its text; photos are added below it). */
function EntryForm({
  projectId,
  entry,
  onDone,
}: {
  projectId: string;
  entry?: Entry;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [key] = useState(newIdempotencyKey);
  const [date, setDate] = useState(entry?.entry_date ?? isoDate(new Date()));
  const [work, setWork] = useState(entry?.work_done ?? "");
  const [workers, setWorkers] = useState(entry?.workers != null ? String(entry.workers) : "");
  const [weather, setWeather] = useState<Weather | "">(entry?.weather ?? "");
  const [holdUps, setHoldUps] = useState(entry?.hold_ups ?? "");
  const [picked, setPicked] = useState<Picked[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: async () => {
      const common = {
        work_done: work.trim(),
        workers: workers ? Number(workers) : null,
        weather: weather || null,
        hold_ups: holdUps.trim() || null,
      };
      if (entry) {
        return unwrap(
          await api.PATCH("/api/v1/diary-entries/{entry_id}", {
            params: { path: { entry_id: entry.id } },
            body: common,
            headers: { "If-Match": ifMatch(entry.version) },
          }),
        );
      }
      setProgress(picked.length ? `Uploading photos: 0 of ${String(picked.length)}` : null);
      const photos = await uploadPhotos(picked, (n) => {
        setProgress(`Uploading photos: ${String(n)} of ${String(picked.length)}`);
      });
      return unwrap(
        await api.POST("/api/v1/projects/{project_id}/diary", {
          params: { path: { project_id: projectId } },
          body: { ...common, entry_date: date, photos },
          headers: { "Idempotency-Key": key },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["diary", projectId] });
      onDone();
    },
    onSettled: () => {
      setProgress(null);
    },
  });
  const okWorkers = workers === "" || /^\d{1,5}$/.test(workers);
  return (
    <form
      aria-label={entry ? "Change the day" : "Write the day"}
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {save.error && (
        <Alert variant="destructive" className="sm:col-span-2">
          <AlertCircle aria-hidden />
          <AlertDescription>{problem(save.error)}</AlertDescription>
        </Alert>
      )}
      {!entry && (
        <Field id="diary-date" label="Day">
          <Input
            id="diary-date"
            type="date"
            value={date}
            max={isoDate(new Date())}
            onChange={(e) => {
              setDate(e.target.value);
            }}
          />
        </Field>
      )}
      <Field id="diary-weather" label="Weather">
        <NativeSelect
          id="diary-weather"
          value={weather}
          onChange={(e) => {
            setWeather(e.target.value as Weather | "");
          }}
        >
          <option value="">–</option>
          {(Object.keys(WEATHER) as Weather[]).map((w) => (
            <option key={w} value={w}>
              {WEATHER[w].label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="diary-workers" label="Workers on site" error={okWorkers ? undefined : "A number"}>
        <Input
          id="diary-workers"
          inputMode="numeric"
          value={workers}
          onChange={(e) => {
            setWorkers(e.target.value);
          }}
        />
      </Field>
      <div className="sm:col-span-2">
        <Field id="diary-work" label="Work done">
          <textarea
            id="diary-work"
            className={TEXTAREA}
            placeholder="e.g. First floor slab shuttering, grids A–C; steel for columns C4–C6 tied"
            value={work}
            onChange={(e) => {
              setWork(e.target.value);
            }}
          />
        </Field>
      </div>
      <div className="sm:col-span-2">
        <Field id="diary-holdups" label="Hold-ups (optional)">
          <textarea
            id="diary-holdups"
            className={TEXTAREA}
            placeholder="Rain, material late, drawings awaited…"
            value={holdUps}
            onChange={(e) => {
              setHoldUps(e.target.value);
            }}
          />
        </Field>
      </div>
      {!entry && (
        <div className="sm:col-span-2">
          <PhotoPicker picked={picked} onChange={setPicked} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
        <Button type="submit" disabled={!work.trim() || !okWorkers || save.isPending}>
          {entry ? "Save" : "Save the day"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        {progress && (
          <span role="status" className="text-muted-foreground text-sm">
            {progress}
          </span>
        )}
      </div>
    </form>
  );
}

function AddPhotos({ entry, projectId }: { entry: Entry; projectId: string }) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Picked[]>([]);
  const add = useMutation({
    mutationFn: async () => {
      const photos = await uploadPhotos(picked, () => undefined);
      return unwrap(
        await api.POST("/api/v1/diary-entries/{entry_id}/photos", {
          params: { path: { entry_id: entry.id } },
          body: { photos },
        }),
      );
    },
    onSuccess: () => {
      setPicked([]);
      void queryClient.invalidateQueries({ queryKey: ["diary", projectId] });
    },
  });
  return (
    <div className="mt-3 grid gap-2">
      <PhotoPicker picked={picked} onChange={setPicked} />
      {picked.length > 0 && (
        <Button
          type="button"
          className="justify-self-start"
          disabled={add.isPending}
          onClick={() => {
            add.mutate();
          }}
        >
          {add.isPending
            ? "Uploading…"
            : `Add ${String(picked.length)} ${picked.length === 1 ? "photo" : "photos"}`}
        </Button>
      )}
      {add.error && <p className="text-destructive text-sm">{problem(add.error)}</p>}
    </div>
  );
}

function Day({
  entry,
  projectId,
  mayWrite,
}: {
  entry: Entry;
  projectId: string;
  mayWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const remove = useMutation({
    mutationFn: async (photoId: string) => {
      unwrap(
        await api.DELETE("/api/v1/diary-photos/{photo_id}", {
          params: { path: { photo_id: photoId } },
        }),
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["diary", projectId] });
    },
  });
  const w = entry.weather ? WEATHER[entry.weather] : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{formatDate(entry.entry_date)}</h2>
        </CardTitle>
        <p className="text-muted-foreground flex flex-wrap items-center gap-3 text-sm">
          {w && (
            <span className="inline-flex items-center gap-1">
              <w.icon className="size-4" aria-hidden /> {w.label}
            </span>
          )}
          {entry.workers != null && (
            <span className="inline-flex items-center gap-1">
              <Users className="size-4" aria-hidden /> {entry.workers} on site
            </span>
          )}
          <span>by {entry.written_by}</span>
        </p>
      </CardHeader>
      <CardContent>
        {editing ? (
          <EntryForm
            projectId={projectId}
            entry={entry}
            onDone={() => {
              setEditing(false);
            }}
          />
        ) : (
          <>
            <p className="text-sm whitespace-pre-line">{entry.work_done}</p>
            {entry.hold_ups && (
              <p className="text-warning mt-2 text-sm whitespace-pre-line">
                <span className="font-medium">Hold-ups: </span>
                {entry.hold_ups}
              </p>
            )}
          </>
        )}
        {entry.photos.length > 0 && (
          <ul
            aria-label={`Photos, ${formatDate(entry.entry_date)}`}
            className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4"
          >
            {entry.photos.map((photo) => (
              <li key={photo.id} className="grid gap-1">
                <a href={photo.url} target="_blank" rel="noreferrer">
                  <img
                    src={photo.url}
                    alt={photo.caption || `Site photo, ${formatDate(entry.entry_date)}`}
                    loading="lazy"
                    className="bg-muted aspect-[4/3] w-full rounded-md object-cover"
                  />
                </a>
                <div className="flex items-start justify-between gap-1">
                  <span className="text-help text-muted-foreground">{photo.caption}</span>
                  {mayWrite && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      aria-label={`Remove photo ${photo.caption ?? ""}`.trim()}
                      onClick={() => {
                        remove.mutate(photo.id);
                      }}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {mayWrite && !editing && (
          <>
            <AddPhotos entry={entry} projectId={projectId} />
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => {
                setEditing(true);
              }}
            >
              Change the text
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function DiaryTab() {
  const { project } = useProjectOutlet();
  const { role } = useSession();
  const mayWrite = can(role, "expenses.record");
  const [writing, setWriting] = useState(false);
  const days = useInfiniteQuery({
    queryKey: ["diary", project.id],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/diary", {
          params: {
            path: { project_id: project.id },
            query: { limit: 20, ...(pageParam ? { cursor: pageParam } : {}) },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const entries = days.data?.pages.flatMap((p) => p.results) ?? [];
  const today = isoDate(new Date());
  const wroteToday = entries.some((e) => e.entry_date === today);
  return (
    <div className="grid max-w-4xl gap-4">
      {mayWrite && !writing && (
        <div>
          <Button
            onClick={() => {
              setWriting(true);
            }}
          >
            {wroteToday ? "Write another day" : "Write today's diary"}
          </Button>
        </div>
      )}
      {writing && (
        <Card>
          <CardContent>
            <EntryForm
              projectId={project.id}
              onDone={() => {
                setWriting(false);
              }}
            />
          </CardContent>
        </Card>
      )}
      {days.isSuccess && entries.length === 0 && !writing && (
        <p className="text-muted-foreground text-sm">
          No diary yet. Write what was done each day, with photos: they are the proof of work for
          your RA bills.
        </p>
      )}
      {entries.map((e) => (
        <Day key={e.id} entry={e} projectId={project.id} mayWrite={mayWrite} />
      ))}
      <LoadMore query={days} />
    </div>
  );
}
