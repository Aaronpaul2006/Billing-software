import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Mail, MessageCircle, Printer } from "lucide-react";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { useSession } from "@/auth/context";
import { Field } from "@/components/FormField";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { usePrintSettings } from "@/features/settings/printSettings";
import { errorMessage } from "@/lib/errors";
import { isBlob } from "@/lib/blob";
import { can } from "@/lib/permissions";

import { documentKey } from "./api";
import type { Document } from "./api";
import { pdfName, whatsappLink, whatsappMessage } from "./sending";
import type { PrintCopy } from "./sending";

function problemText(e: unknown): string {
  if (e instanceof ApiError) {
    return e.problem.errors?.length ? e.problem.errors.map((x) => x.message).join(" ") : e.message;
  }
  return errorMessage(e);
}

/** Email the PDF to the client: To (the client's address), an optional note. */
function EmailDialog({
  doc,
  copy,
  onClose,
  onSent,
}: {
  doc: Document;
  copy: PrintCopy;
  onClose: () => void;
  onSent: (to: string) => void;
}) {
  const queryClient = useQueryClient();
  const [to, setTo] = useState<string | null>(null); // null: not typed yet, use the client's
  const [note, setNote] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [problem, setProblem] = useState<string | null>(null);
  const client = useQuery(clientQuery(doc.party_id));
  const address = to ?? client.data?.email ?? "";
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/documents/{document_id}/email", {
          params: { path: { document_id: doc.id } },
          body: { to: address.trim() || null, copy, message: note.trim() || null },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: (sent) => {
      setKey(newIdempotencyKey());
      void queryClient.invalidateQueries({ queryKey: documentKey(doc.id) }); // its history
      onSent(sent.sent_to);
    },
    onError: (e) => {
      setProblem(problemText(e));
    },
  });
  return (
    <Modal title="Email the bill" onClose={onClose}>
      <form
        aria-label="Email the bill"
        className="grid gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setProblem(null);
          send.mutate();
        }}
      >
        <Field id="email-to" label="To" hint="The PDF is attached; replies come to you.">
          <Input
            id="email-to"
            type="email"
            value={address}
            onChange={(e) => {
              setTo(e.target.value);
            }}
          />
        </Field>
        <Field id="email-note" label="Note (optional)">
          <textarea
            id="email-note"
            rows={3}
            className="border-input rounded-md border bg-transparent px-3 py-2 text-sm"
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
        </Field>
        {problem && <p className="text-destructive text-sm">{problem}</p>}
        <div className="flex gap-2">
          <Button type="submit" disabled={send.isPending || address.trim() === ""}>
            <Mail aria-hidden /> Send
          </Button>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** The client's email and phone, fetched when first needed. */
function clientQuery(partyId: string) {
  return {
    queryKey: ["parties", partyId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties/{party_id}", { params: { path: { party_id: partyId } } }),
      ),
  };
}

/**
 * Print, download, email or WhatsApp an issued bill (B.15). All of them use
 * the copy chosen next to the PDF button (Original for recipient if none).
 */
export function SendBill({ doc, copy }: { doc: Document; copy: PrintCopy }) {
  const { role } = useSession();
  const queryClient = useQueryClient();
  const settings = usePrintSettings();
  const [emailing, setEmailing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const pdf = async (): Promise<Blob> => {
    const { data, response } = await api.GET("/api/v1/documents/{document_id}/pdf", {
      params: { path: { document_id: doc.id }, query: { copy } },
      parseAs: "blob",
    });
    if (!response.ok || !isBlob(data)) throw new Error("The PDF could not be made.");
    return data;
  };
  const download = async () => {
    const url = URL.createObjectURL(await pdf());
    const a = document.createElement("a");
    a.href = url;
    a.download = pdfName(doc, copy);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 60_000);
  };
  const run = (what: () => Promise<void>) => {
    setNotice(null);
    what().catch((e: unknown) => {
      setNotice(problemText(e));
    });
  };

  const print = async () => {
    const url = URL.createObjectURL(await pdf());
    const frame = document.createElement("iframe");
    frame.title = "Bill to print";
    frame.style.display = "none";
    frame.src = url;
    frame.onload = () => {
      frame.contentWindow?.print();
    };
    document.body.appendChild(frame);
  };
  const whatsapp = async () => {
    const tab = window.open("", "_blank"); // opened now, so pop-up blockers allow it
    try {
      const client = await queryClient.query(clientQuery(doc.party_id));
      await download(); // staff attach it in WhatsApp
      const link = whatsappLink(client.phone, whatsappMessage(doc, settings.data?.upi_id));
      if (tab) tab.location.href = link;
      setNotice("The PDF was downloaded: attach it in WhatsApp.");
    } catch (e) {
      tab?.close();
      throw e;
    }
  };

  return (
    <div className="grid gap-2">
      <div role="group" aria-label="Send or print" className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          onClick={() => {
            run(print);
          }}
        >
          <Printer aria-hidden /> Print
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            run(download);
          }}
        >
          <Download aria-hidden /> Download
        </Button>
        {can(role, "documents.issue") && (
          <Button
            variant="outline"
            onClick={() => {
              setNotice(null);
              setEmailing(true);
            }}
          >
            <Mail aria-hidden /> Email…
          </Button>
        )}
        <Button
          variant="outline"
          onClick={() => {
            run(whatsapp);
          }}
        >
          <MessageCircle aria-hidden /> WhatsApp
        </Button>
      </div>
      {notice && (
        <p role="status" className="text-muted-foreground text-sm">
          {notice}
        </p>
      )}
      {emailing && (
        <EmailDialog
          doc={doc}
          copy={copy}
          onClose={() => {
            setEmailing(false);
          }}
          onSent={(to) => {
            setEmailing(false);
            setNotice(`Sent to ${to}.`);
          }}
        />
      )}
    </div>
  );
}
