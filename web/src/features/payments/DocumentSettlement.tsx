import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/errors";
import { compareMoney, formatInr } from "@/lib/money";

import { allocationProblems, toAllocationItems, useOpenItems } from "./allocations";
import type { Allocations } from "./allocations";
import { AllocationTable } from "./AllocationTable";

function settlementKey(id: string) {
  return ["document-allocations", id] as const;
}

function ApplyCreditNote({
  noteId,
  partyId,
  unapplied,
}: {
  noteId: string;
  partyId: string;
  unapplied: string;
}) {
  const queryClient = useQueryClient();
  const [allocations, setAllocations] = useState<Allocations>({});
  const [key, setKey] = useState(newIdempotencyKey);
  const [error, setError] = useState<string | null>(null);
  const open = useOpenItems(partyId, false); // credit notes settle documents, not releases
  const problems = allocationProblems(open.data ?? [], allocations, unapplied);
  const apply = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/allocations", {
          params: { path: { document_id: noteId } },
          body: { allocations: toAllocationItems(allocations) },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (result) => {
      setKey(newIdempotencyKey());
      setAllocations({});
      queryClient.setQueryData(settlementKey(noteId), result);
      void queryClient.invalidateQueries({ queryKey: ["open-items"] });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document"] });
    },
    onError: (e) => {
      setError(
        e instanceof ApiError && e.problem.errors?.length
          ? e.problem.errors.map((x) => x.message).join(" ")
          : errorMessage(e),
      );
    },
  });
  return (
    <div className="grid gap-3">
      <h3 className="text-sm font-medium">Apply to invoices</h3>
      <AllocationTable
        items={open.data ?? []}
        allocations={allocations}
        onChange={setAllocations}
        available={unapplied}
        isLoading={open.isPending}
        error={open.error}
      />
      {[...problems, ...(error ? [error] : [])].map((p) => (
        <p key={p} className="text-destructive text-sm">
          {p}
        </p>
      ))}
      <div>
        <Button
          disabled={
            apply.isPending || problems.length > 0 || toAllocationItems(allocations).length === 0
          }
          onClick={() => {
            setError(null);
            apply.mutate();
          }}
        >
          Apply
        </Button>
      </div>
    </div>
  );
}

/** What settled an issued document; for a credit note, what it was applied to. */
export function DocumentSettlement({
  documentId,
  partyId,
}: {
  documentId: string;
  partyId: string;
}) {
  const settlement = useQuery({
    queryKey: settlementKey(documentId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{document_id}/allocations", {
          params: { path: { document_id: documentId } },
        }),
      ),
  });
  if (settlement.error) return <ErrorState error={settlement.error} />;
  if (!settlement.data) return <Skeleton className="h-20 w-full" />;
  const s = settlement.data;
  const isNote = s.doc_type === "CREDIT_NOTE";
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{isNote ? "Applied to" : "Settled by"}</h2>
        </CardTitle>
        {isNote && s.applied !== null && s.unapplied !== null && (
          <CardDescription>
            Applied {formatInr(s.applied)}, still available {formatInr(s.unapplied)}.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="grid gap-6">
        {s.allocations.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {isNote ? "Not applied to any invoice yet." : "Nothing received against it yet."}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{isNote ? "Invoice" : "From"}</TableHead>
                <TableHead>On</TableHead>
                <TableHead className="text-right">Amount</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {s.allocations.map((a) => (
                <TableRow key={a.id}>
                  <TableCell>
                    {isNote ? (
                      <Link to={`/documents/${a.document_id ?? ""}`} className="hover:underline">
                        {a.doc_number}
                      </Link>
                    ) : a.payment_id ? (
                      <Link to={`/payments/${a.payment_id}`} className="hover:underline">
                        Payment
                      </Link>
                    ) : (
                      <Link to={`/documents/${a.credit_note_id ?? ""}`} className="hover:underline">
                        Credit note
                      </Link>
                    )}
                  </TableCell>
                  <TableCell>{a.created_at.slice(0, 10)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatInr(a.amount)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {isNote && s.unapplied !== null && compareMoney(s.unapplied, "0") === 1 && (
          <ApplyCreditNote noteId={documentId} partyId={partyId} unapplied={s.unapplied} />
        )}
      </CardContent>
    </Card>
  );
}
