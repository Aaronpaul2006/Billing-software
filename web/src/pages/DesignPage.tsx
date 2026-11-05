import { AlertCircle, CheckCircle2, Plus, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { useConfirm } from "@/components/confirm-context";
import { Field } from "@/components/FormField";
import { FormSection } from "@/components/FormSection";
import { Money, MoneyCell } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SaveBar } from "@/components/SaveBar";
import { StatusBadge } from "@/components/StatusBadge";
import { STATUS_TEXT } from "@/components/status";
import type { Status } from "@/components/status";
import { useToast } from "@/components/toast-context";
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
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { setThemeChoice, themeChoice } from "@/lib/appearance";

const COLOURS = [
  ["background", "bg-background"],
  ["card", "bg-card"],
  ["muted", "bg-muted"],
  ["primary", "bg-primary"],
  ["secondary", "bg-secondary"],
  ["accent", "bg-accent"],
  ["success", "bg-success"],
  ["warning", "bg-warning"],
  ["destructive", "bg-destructive"],
  ["info", "bg-info"],
  ["success-soft", "bg-success-soft"],
  ["warning-soft", "bg-warning-soft"],
  ["destructive-soft", "bg-destructive-soft"],
  ["info-soft", "bg-info-soft"],
  ["border", "bg-border"],
  ["input (form borders)", "bg-input"],
] as const;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="grid gap-3">
      <h2 className="text-section font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/**
 * The living style guide (D.3): every shared component and state, in light
 * and dark. Development only (and builds made with VITE_DESIGN_PAGE=true).
 */
export function DesignPage() {
  const confirm = useConfirm();
  const toast = useToast();
  const [theme, setTheme] = useState(themeChoice);
  const [answer, setAnswer] = useState("");
  return (
    <main className="mx-auto grid max-w-5xl gap-10 p-4 pb-0 md:p-8 md:pb-0">
      <PageHeader
        title="Design system"
        badges={<StatusBadge status="issued">Living style guide</StatusBadge>}
        description="Tokens from src/index.css and the shared components in src/components."
        actions={
          <NativeSelect
            aria-label="Theme"
            value={theme}
            onChange={(e) => {
              const next = e.target.value as typeof theme;
              setThemeChoice(next);
              setTheme(next);
            }}
          >
            <option value="system">Same as this device</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </NativeSelect>
        }
      />

      <Section title="Colours">
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {COLOURS.map(([name, cls]) => (
            <li key={name} className="grid gap-1 text-sm">
              <span className={`${cls} h-12 rounded-lg border`} />
              {name}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Type">
        <div className="grid gap-2">
          <p className="text-title font-semibold">Page title · text-title</p>
          <p className="text-section font-semibold">Section title · text-section</p>
          <p className="text-figure font-semibold">
            <Money value="1397875.18" /> · text-figure
          </p>
          <p>Body text, 16 px. ഇത് മലയാളം ആണ്. यह हिन्दी है।</p>
          <p className="text-sm">Small text and labels, 14 px.</p>
          <p className="text-help text-muted-foreground">Help text under a field, 13 px.</p>
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-2">
          <Button>
            <Plus aria-hidden /> Primary
          </Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="link">Link</Button>
          <Button variant="destructive">
            <Trash2 aria-hidden /> Delete
          </Button>
          <Button disabled>Disabled</Button>
          <Button size="sm">Small</Button>
          <Button size="icon" aria-label="Save">
            <Save aria-hidden />
          </Button>
        </div>
      </Section>

      <Section title="Status badges (one colour meaning each)">
        <div className="flex flex-wrap gap-2">
          {(Object.keys(STATUS_TEXT) as Status[]).map((s) => (
            <StatusBadge key={s} status={s} />
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>Default</Badge>
          <Badge variant="secondary">Customer</Badge>
          <Badge variant="outline">Vendor</Badge>
        </div>
      </Section>

      <Section title="Amounts">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Bill</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Outstanding</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>INV/0002</TableCell>
              <MoneyCell value="410672.56" />
              <MoneyCell value="186310.18" />
            </TableRow>
            <TableRow>
              <TableCell>INV/0001</TableCell>
              <MoneyCell value="575132.00" />
              <MoneyCell value="0.00" muted />
            </TableRow>
          </TableBody>
          <TableFooter>
            <TableRow>
              <TableCell>Total</TableCell>
              <MoneyCell value="985804.56" strong />
              <MoneyCell value="186310.18" strong />
            </TableRow>
          </TableFooter>
        </Table>
      </Section>

      <Section title="Cards, alerts and loading">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Card title</CardTitle>
              <CardDescription>A line about what the card holds.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </CardContent>
          </Card>
          <div className="grid content-start gap-3">
            <Alert>
              <CheckCircle2 aria-hidden />
              <AlertDescription>Saved. New PDFs use these settings.</AlertDescription>
            </Alert>
            <Alert variant="destructive">
              <AlertCircle aria-hidden />
              <AlertDescription>The bill could not be issued: no number series.</AlertDescription>
            </Alert>
          </div>
        </div>
      </Section>

      <Section title="Confirm dialog and messages">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            onClick={() => {
              void confirm({
                title: "Delete this draft?",
                description: "The draft is removed for good. Issued bills are never deleted.",
                confirmLabel: "Delete draft",
                tone: "danger",
              }).then((yes) => {
                setAnswer(yes ? "You chose to delete." : "You kept it.");
              });
            }}
          >
            Ask to confirm
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              toast({ message: "Payment recorded." });
            }}
          >
            Show a message
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              toast({
                message: "Line 3 removed: Plastering.",
                tone: "info",
                action: {
                  label: "Undo",
                  onClick: () => {
                    setAnswer("Line 3 is back.");
                  },
                },
              });
            }}
          >
            Message with Undo
          </Button>
          {answer && <span className="text-muted-foreground text-sm">{answer}</span>}
        </div>
      </Section>

      <Section title="Form section and Save bar">
        <FormSection
          title="Bank details"
          description="Printed on every bill, with the UPI QR code."
        >
          <Field id="d-bank" label="Bank">
            <Input id="d-bank" defaultValue="State Bank of India" />
          </Field>
          <Field id="d-ifsc" label="IFSC" hint="Like SBIN0001234.">
            <Input id="d-ifsc" defaultValue="SBIN0070123" />
          </Field>
          <Field id="d-acc" label="Account number" error="An account number is 6 to 18 digits.">
            <Input id="d-acc" defaultValue="12AB" aria-invalid />
          </Field>
        </FormSection>
        <SaveBar status="Unsaved changes">
          <Button variant="ghost">Cancel</Button>
          <Button>Save</Button>
        </SaveBar>
      </Section>
    </main>
  );
}
