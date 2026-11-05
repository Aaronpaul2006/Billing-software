import { Check, Mail, Phone } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { BRAND } from "@/brand";
import { BrandMark } from "@/components/BrandMark";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** What a careful owner wants to know before signing up (all true of this app). */
const TRUST = [
  "Each business's data is kept apart from every other's",
  "Owners and admins sign in with a second step (an app code)",
  "GST worked out exactly: CGST and SGST or IGST, RA bills, retention, TDS",
  "Take your data out any time: Tally, Excel and PDF",
];

/**
 * The frame of every signed-out page (D.13): the brand and a way back to the
 * home page; on wide screens a brand panel with what the app promises and how
 * to reach us.
 */
export function AuthShell({ children }: { children: ReactNode }) {
  const { contact } = BRAND;
  return (
    <div className="bg-muted grid min-h-svh lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <aside className="bg-primary text-primary-foreground hidden flex-col justify-between gap-10 p-10 lg:flex">
        <Link to="/" className="w-fit rounded-md">
          <BrandMark inverted className="text-lg" />
          <span className="sr-only">, home page</span>
        </Link>
        <div className="grid max-w-md gap-6">
          <p className="text-3xl font-semibold tracking-tight">{BRAND.tagline}</p>
          <ul className="grid gap-3">
            {TRUST.map((t) => (
              <li key={t} className="flex gap-3">
                <Check className="mt-0.5 size-5 shrink-0" aria-hidden />
                {t}
              </li>
            ))}
          </ul>
        </div>
        <p className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <span className="flex items-center gap-2">
            <Phone className="size-4" aria-hidden /> {contact.phone}
          </span>
          <span className="flex items-center gap-2">
            <Mail className="size-4" aria-hidden /> {contact.email}
          </span>
        </p>
      </aside>
      <main className="flex flex-col items-center justify-center gap-6 p-4">
        <Link to="/" className="rounded-md lg:hidden">
          <BrandMark className="text-lg" />
          <span className="sr-only">, home page</span>
        </Link>
        {children}
      </main>
    </div>
  );
}

/** The centred card the signed-out pages use (sign up, password reset, email links). */
export function AuthCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <AuthShell>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-xl">{title}</h1>
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent className="grid gap-4">{children}</CardContent>
      </Card>
    </AuthShell>
  );
}
