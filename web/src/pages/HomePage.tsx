import {
  BarChart3,
  Calculator,
  ClipboardList,
  Download,
  FileText,
  IndianRupee,
  LockKeyhole,
  Mail,
  MessageCircle,
  Phone,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { BRAND } from "@/brand";
import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: FileText,
    title: "GST and non-GST bills",
    text: "Tax invoices, bills of supply, quotations, proformas, credit and debit notes. CGST / SGST or IGST worked out from the place of supply, with gapless numbering for each GSTIN and year.",
  },
  {
    icon: ClipboardList,
    title: "RA bills against your BOQ",
    text: "Import the bill of quantities, bill each running account against it, and see what is billed and what is left for every item.",
  },
  {
    icon: IndianRupee,
    title: "Payments, retention and TDS",
    text: "Record payments against bills, track retention held and released, mobilisation advance recovery, and TDS deducted by your clients.",
  },
  {
    icon: Users,
    title: "A portal for your clients",
    text: "Clients sign in to see their bills, payments, statement and project progress, and accept your quotations online.",
  },
  {
    icon: BarChart3,
    title: "Dashboard and reports",
    text: "Billed, collected, overdue and margin at a glance; GST summary, receivables by age, project profit and Excel exports.",
  },
  {
    icon: ShieldCheck,
    title: "Your team, your rules",
    text: "Owner, admin, accountant, site engineer and viewer roles; two-step sign-in; every change kept in an audit log.",
  },
];

const STEPS: { title: string; text: string; screen: ReactNode }[] = [
  {
    title: "Set up your company",
    text: "Add your GSTIN, your number series and your team.",
    screen: (
      <MockScreen title="GST registrations">
        <MockRow left="32ABCDE1234F1Z5 · Kerala" right="Default" />
        <MockRow left="Series INV/2026/" right="Next: 0001" />
      </MockScreen>
    ),
  },
  {
    title: "Add clients and projects",
    text: "Each project with its client, contract value, retention and BOQ.",
    screen: (
      <MockScreen title="Villa project · BOQ">
        <MockRow left="RCC work · 120 cum" right="62 % billed" />
        <MockRow left="Brickwork · 300 sqm" right="35 % billed" />
      </MockScreen>
    ),
  },
  {
    title: "Send bills and quotations",
    text: "Issue a bill in a minute; the PDF goes to your client.",
    screen: (
      <MockScreen title="Tax invoice INV/2026/0042">
        <MockRow left="Taxable value" right="₹2,89,000.00" />
        <MockRow left="CGST + SGST 18 %" right="₹52,020.00" />
        <MockRow left="Total" right="₹3,41,020.00" strong />
      </MockScreen>
    ),
  },
  {
    title: "Get paid and follow up",
    text: "Record payments, send reminders, watch what is overdue.",
    screen: (
      <MockScreen title="Dashboard">
        <MockRow left="Collected this year" right="₹48,20,000.00" />
        <MockRow left="Overdue" right="₹3,12,500.00" warn />
      </MockScreen>
    ),
  },
];

const FAQ: { q: string; a: string }[] = [
  {
    q: "Does it follow Indian GST rules?",
    a: "Yes. Intra-state bills get CGST and SGST, inter-state bills IGST, decided from the place of supply. Reverse charge, SEZ and export supplies (with or without a Letter of Undertaking) are supported, and issued bills cannot be edited: corrections are credit or debit notes, as the law expects.",
  },
  {
    q: "Can I bill without GST?",
    a: "Yes. Bills of supply, estimates and quotations sit in a separate non-GST book, and reports show each book on its own or both together.",
  },
  {
    q: "Is my data safe and private?",
    a: "Each company's data is kept apart by the database itself, not only by the app. Sign-in can use a second step, sessions can be ended from any device, and every change is recorded.",
  },
  {
    q: "What can my clients see?",
    a: "Only their own issued bills, payments, statement and project progress, after signing in with a code we email them. Never your other clients, your costs or your drafts.",
  },
  {
    q: "Can my team use it?",
    a: "Yes. Invite people as owner, admin, accountant, site engineer or viewer. A site engineer can prepare bills and BOQ measurements; only accountants and above issue them.",
  },
];

/** What a careful owner wants to know (D.13); every point is true of the app today. */
const TRUST: { icon: LucideIcon; title: string; text: string }[] = [
  {
    icon: LockKeyhole,
    title: "Only your business sees your books",
    text: "Each business's data is kept apart in the database itself, not just on the screen.",
  },
  {
    icon: ShieldCheck,
    title: "Two-step sign-in",
    text: "Owners and admins confirm each sign-in with a code from an app; clients with a code by email.",
  },
  {
    icon: Calculator,
    title: "Exact to the paisa",
    text: "Amounts are worked out exactly, never rounded along the way, and GST follows the place of supply.",
  },
  {
    icon: Download,
    title: "Your data, any time",
    text: "Export to Tally, Excel or PDF whenever you like; nothing is locked in.",
  },
];

function MockScreen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="bg-background rounded-lg border p-3 text-xs shadow-sm" aria-hidden>
      <div className="text-muted-foreground mb-2 truncate font-medium">{title}</div>
      <div className="grid gap-1">{children}</div>
    </div>
  );
}

function MockRow({
  left,
  right,
  strong,
  warn,
}: {
  left: string;
  right: string;
  strong?: boolean;
  warn?: boolean;
}) {
  return (
    <div className="bg-muted flex justify-between gap-2 rounded px-2 py-1">
      <span className="truncate">{left}</span>
      <span
        className={
          strong
            ? "font-semibold tabular-nums"
            : warn
              ? "text-destructive font-medium tabular-nums" // AA contrast on the grey row
              : "tabular-nums"
        }
      >
        {right}
      </span>
    </div>
  );
}

/** The public home page, for visitors who are not signed in. */
export function HomePage() {
  const { contact } = BRAND;
  return (
    <div className="bg-background min-h-svh">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 p-4">
          <Link to="/" className="rounded-md">
            <BrandMark />
          </Link>
          <nav aria-label="Home" className="flex items-center gap-1 text-sm">
            <a href="#features" className="hover:bg-accent hidden rounded-md px-3 py-1.5 sm:block">
              Features
            </a>
            <a href="#how" className="hover:bg-accent hidden rounded-md px-3 py-1.5 sm:block">
              How it works
            </a>
            <a href="#contact" className="hover:bg-accent hidden rounded-md px-3 py-1.5 sm:block">
              Contact
            </a>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
            <Button size="sm" asChild>
              <Link to="/signup">Create your account</Link>
            </Button>
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 md:grid-cols-2 md:py-24">
          <div className="grid gap-6">
            <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">{BRAND.tagline}</h1>
            <p className="text-muted-foreground text-lg">{BRAND.description}</p>
            <div className="flex flex-wrap gap-3">
              <Button size="lg" asChild>
                <Link to="/signup">Create your account</Link>
              </Button>
              <Button size="lg" variant="outline" asChild>
                <Link to="/login">Sign in</Link>
              </Button>
            </div>
          </div>
          <div className="bg-muted grid gap-3 rounded-2xl p-6">
            {STEPS[2]?.screen}
            {STEPS[3]?.screen}
          </div>
        </section>

        <section id="features" aria-labelledby="features-title" className="bg-muted/50 border-y">
          <div className="mx-auto max-w-6xl px-4 py-16">
            <h2 id="features-title" className="mb-8 text-2xl font-semibold tracking-tight">
              Everything a construction business bills
            </h2>
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map(({ icon: Icon, title, text }) => (
                <div
                  key={title}
                  className="bg-background grid content-start gap-2 rounded-xl border p-5"
                >
                  <Icon className="size-5" aria-hidden />
                  <h3 className="font-medium">{title}</h3>
                  <p className="text-muted-foreground text-sm">{text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="how" aria-labelledby="how-title" className="mx-auto max-w-6xl px-4 py-16">
          <h2 id="how-title" className="mb-8 text-2xl font-semibold tracking-tight">
            How it works
          </h2>
          <ol className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((step, i) => (
              <li key={step.title} className="grid content-start gap-3">
                <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-full text-sm font-semibold">
                  {i + 1}
                </span>
                <h3 className="font-medium">{step.title}</h3>
                <p className="text-muted-foreground text-sm">{step.text}</p>
                {step.screen}
              </li>
            ))}
          </ol>
        </section>

        <section id="trust" aria-labelledby="trust-title" className="mx-auto max-w-6xl px-4 py-16">
          <h2 id="trust-title" className="mb-8 text-2xl font-semibold tracking-tight">
            Your books, kept safe
          </h2>
          <ul className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {TRUST.map(({ icon: Icon, title, text }) => (
              <li key={title} className="grid content-start gap-2">
                <span className="bg-primary/10 text-primary flex size-9 items-center justify-center rounded-lg">
                  <Icon className="size-5" aria-hidden />
                </span>
                <h3 className="font-medium">{title}</h3>
                <p className="text-muted-foreground text-sm">{text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section id="faq" aria-labelledby="faq-title" className="bg-muted/50 border-y">
          <div className="mx-auto max-w-6xl px-4 py-16">
            <h2 id="faq-title" className="mb-6 text-2xl font-semibold tracking-tight">
              Questions
            </h2>
            <div className="grid items-start gap-2 md:grid-cols-2">
              {FAQ.map(({ q, a }) => (
                <details key={q} className="bg-background group rounded-lg border p-4">
                  <summary className="cursor-pointer font-medium">{q}</summary>
                  <p className="text-muted-foreground mt-2 text-sm">{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section
          id="contact"
          aria-labelledby="contact-title"
          className="mx-auto max-w-6xl px-4 py-16"
        >
          <h2 id="contact-title" className="mb-2 text-2xl font-semibold tracking-tight">
            Talk to us
          </h2>
          <p className="text-muted-foreground mb-6">
            Questions, a walk-through, or help moving your bills across: we are happy to help.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" asChild>
              <a href={`tel:${contact.phone.replace(/\s/g, "")}`}>
                <Phone aria-hidden /> {contact.phone}
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href={`https://wa.me/${contact.whatsapp}`} target="_blank" rel="noreferrer">
                <MessageCircle aria-hidden /> WhatsApp
              </a>
            </Button>
            <Button variant="outline" asChild>
              <a href={`mailto:${contact.email}`}>
                <Mail aria-hidden /> {contact.email}
              </a>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="text-muted-foreground mx-auto flex max-w-6xl flex-wrap justify-between gap-2 p-4 text-sm">
          <span>
            © {new Date().getFullYear()} {BRAND.name}
          </span>
          <span className="flex gap-4">
            <Link to="/login" className="hover:underline">
              Sign in
            </Link>
            <Link to="/signup" className="hover:underline">
              Create your account
            </Link>
          </span>
        </div>
      </footer>
    </div>
  );
}
