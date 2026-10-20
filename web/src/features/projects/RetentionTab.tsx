import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { isoDate } from "@/features/dashboard/periods";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";
import { cleanMoneyInput, compareMoney, formatInr, MONEY_INPUT } from "@/lib/money";

import { useProjectOutlet } from "./api";

type Release = components["schemas"]["RetentionRelease"];
type Book = components["schemas"]["RetentionBookEnum"];

function problemText(e: unknown): string {
  if (e instanceof ApiError && e.problem.errors?.length) {
    return e.problem.errors.map((x) => x.message).join(" ");
  }
  if (e instanceof ApiError && e.code === "release_settled") {
    return "Payments are allocated to this release; unwind them on the payment first.";
  }
  return errorMessage(e);
}

function NewRelease({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [book, setBook] = useState<Book>("GST");
  const [amount, setAmount] = useState("");
  const [releaseDate, setReleaseDate] = useState(() => isoDate(new Date()));
  const [dueDate, setDueDate] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey);
  const cleaned = cleanMoneyInput(amount);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/retention-releases", {
          body: {
            project_id: projectId,
            book,
            release_date: releaseDate,
            due_date: dueDate || null,
            amount: cleaned,
            reference: reference.trim() || null,
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["retention", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["releases", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["open-items"] });
      onDone();
    },
    onError: (e) => {
      setError(problemText(e));
    },
  });
  return (
    <form
      aria-label="New retention release"
      className="bg-muted/40 grid gap-4 rounded-lg border p-4 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        if (!MONEY_INPUT.test(cleaned)) {
          setError("Enter the amount the client releases, e.g. 20000.");
          return;
        }
        save.mutate();
      }}
    >
      {error && (
        <Alert variant="destructive" className="sm:col-span-3">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Field id="release-amount" label="Amount released (₹)">
        <Input
          id="release-amount"
          inputMode="decimal"
          value={amount}
          onChange={(e) => {
            setAmount(e.target.value);
          }}
        />
      </Field>
      <Field id="release-book" label="From retention on">
        <NativeSelect
          id="release-book"
          value={book}
          onChange={(e) => {
            setBook(e.target.value as Book);
          }}
        >
          <option value="GST">Tax invoices (GST)</option>
          <option value="NON_GST">Bills of supply</option>
        </NativeSelect>
      </Field>
      <Field id="release-ref" label="Reference" hint="e.g. the client's release letter.">
        <Input
          id="release-ref"
          value={reference}
          onChange={(e) => {
            setReference(e.target.value);
          }}
        />
      </Field>
      <Field id="release-date" label="Release date">
        <Input
          id="release-date"
          type="date"
          value={releaseDate}
          onChange={(e) => {
            setReleaseDate(e.target.value);
          }}
        />
      </Field>
      <Field id="release-due" label="Due date">
        <Input
          id="release-due"
          type="date"
          value={dueDate}
          onChange={(e) => {
            setDueDate(e.target.value);
          }}
        />
      </Field>
      <div className="flex items-end gap-2">
        <Button type="submit" disabled={save.isPending}>
          Record release
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function CancelRelease({ release, onDone }: { release: Release; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey);
  const cancel = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/retention-releases/{release_id}/cancel", {
          params: { path: { release_id: release.id } },
          body: { reason: reason.trim() },
          headers: { "If-Match": ifMatch(release.version), "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["retention", release.project_id] });
      void queryClient.invalidateQueries({ queryKey: ["releases", release.project_id] });
      onDone();
    },
    onError: (e) => {
      setError(problemText(e));
    },
  });
  return (
    <form
      aria-label="Cancel release"
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        cancel.mutate();
      }}
    >
      <Field id={`cancel-${release.id}`} label="Reason">
        <Input
          id={`cancel-${release.id}`}
          value={reason}
          onChange={(e) => {
            setReason(e.target.value);
          }}
        />
      </Field>
      <Button
        type="submit"
        variant="destructive"
        size="sm"
        disabled={reason.trim().length < 3 || cancel.isPending}
      >
        Cancel release
      </Button>
      <Button type="button" variant="ghost" size="sm" onClick={onDone}>
        Keep it
      </Button>
      {error && <p className="text-destructive w-full text-sm">{error}</p>}
    </form>
  );
}

export function RetentionTab() {
  const { project } = useProjectOutlet();
  const [adding, setAdding] = useState(false);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const held = useQuery({
    queryKey: ["retention", project.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/retention", {
          params: { path: { project_id: project.id } },
        }),
      ),
  });
  const releases = useQuery({
    queryKey: ["releases", project.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/retention-releases", {
          params: { query: { project_id: project.id, ordering: "-release_date", limit: 100 } },
        }),
      ).results,
  });
  const books = held.data
    ? ([
        ["Tax invoices (GST)", held.data.GST],
        ["Bills of supply", held.data.NON_GST],
      ] as const)
    : [];

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Retention</h2>
          </CardTitle>
          <CardDescription>
            Held back from your bills until the client releases it. A release is money now due,
            collected with a payment; GST was charged on the bills already.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {held.error ? (
            <ErrorState error={held.error} />
          ) : !held.data ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>From</TableHead>
                  <TableHead className="text-right">Deducted</TableHead>
                  <TableHead className="text-right">Released</TableHead>
                  <TableHead className="text-right">Still held</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {books.map(([label, b]) => (
                  <TableRow key={label}>
                    <TableCell>{label}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatInr(b.deducted)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatInr(b.released)}
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatInr(b.available)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Releases</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {adding ? (
            <NewRelease
              projectId={project.id}
              onDone={() => {
                setAdding(false);
              }}
            />
          ) : (
            <div>
              <Button
                onClick={() => {
                  setAdding(true);
                }}
              >
                Record release
              </Button>
            </div>
          )}
          {releases.error ? (
            <ErrorState error={releases.error} />
          ) : !releases.data ? (
            <Skeleton className="h-16 w-full" />
          ) : releases.data.length === 0 ? (
            <p className="text-muted-foreground text-sm">No retention released yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Released</TableHead>
                  <TableHead>Reference</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="text-right">Still owed</TableHead>
                  <TableHead>
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {releases.data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      {r.release_date}
                      <div className="text-muted-foreground text-xs">
                        {r.book === "GST" ? "GST" : "Non-GST"}
                      </div>
                    </TableCell>
                    <TableCell>{r.reference ?? "–"}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatInr(r.amount)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.status === "CANCELLED" ? (
                        <Badge variant="secondary">Cancelled</Badge>
                      ) : compareMoney(r.outstanding, "0") === 1 ? (
                        formatInr(r.outstanding)
                      ) : (
                        "Paid"
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {r.status === "RELEASED" &&
                        (cancelling === r.id ? (
                          <CancelRelease
                            release={r}
                            onDone={() => {
                              setCancelling(null);
                            }}
                          />
                        ) : (
                          <div className="flex justify-end gap-1">
                            {compareMoney(r.outstanding, "0") === 1 && (
                              <Button variant="ghost" size="sm" asChild>
                                <Link to="/payments/new">Record payment</Link>
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                setCancelling(r.id);
                              }}
                            >
                              Cancel…
                            </Button>
                          </div>
                        ))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
