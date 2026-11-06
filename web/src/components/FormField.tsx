import type { ComponentProps, ReactNode } from "react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** A labelled control with its error (or hint) below, wired for screen readers. */
export function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  error?: string | undefined;
  hint?: string | undefined;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("grid content-start gap-2", className)}>
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
