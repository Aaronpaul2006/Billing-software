import type { ComponentProps, ReactNode } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** A labelled control with its error (or hint) below, wired for screen readers. */
export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string | undefined;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p className="text-destructive text-sm" id={`${id}-error`}>
          {error}
        </p>
      ) : (
        hint && <p className="text-muted-foreground text-xs">{hint}</p>
      )}
    </div>
  );
}

export function TextField({
  id,
  label,
  error,
  hint,
  registration,
  ...input
}: {
  id: string;
  label: string;
  error?: string | undefined;
  hint?: string;
  registration: UseFormRegisterReturn;
} & Omit<ComponentProps<"input">, "id">) {
  return (
    <Field id={id} label={label} error={error} {...(hint ? { hint } : {})}>
      <Input
        id={id}
        aria-invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        {...input}
        {...registration}
      />
    </Field>
  );
}
