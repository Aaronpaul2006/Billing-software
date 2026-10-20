import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router";
import { z } from "zod";

import { useAuth } from "@/auth/context";
import { TextField } from "@/components/FormField";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { applyServerErrors } from "@/lib/forms";

import { AuthCard } from "./AuthCard";

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter your name."),
  business_name: z.string().trim().min(1, "Enter the name of your business."),
  email: z.string().trim().pipe(z.email("Enter your email address.")),
  password: z.string().min(10, "Use at least 10 characters."),
});
type Values = z.infer<typeof schema>;
const FIELDS = ["full_name", "business_name", "email", "password"] as const;

/** Create an account and its first company. The owner then sets up two-step
 * verification (RequireAuth sends them there) and confirms their email. */
export function SignupPage() {
  const { state, signup } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", business_name: "", email: "", password: "" },
  });
  const errors = form.formState.errors;

  if (state.status === "signed_in") return <Navigate to="/" replace />;

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await signup(values);
      void navigate("/", { replace: true });
    } catch (e) {
      setError(applyServerErrors(e, form.setError, FIELDS));
    }
  });

  return (
    <AuthCard title="Create your account" description="Construction billing">
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <form onSubmit={(e) => void onSubmit(e)} className="grid gap-4" noValidate>
        <TextField
          id="full_name"
          label="Your name"
          autoComplete="name"
          autoFocus
          error={errors.full_name?.message}
          registration={form.register("full_name")}
        />
        <TextField
          id="business_name"
          label="Business name"
          autoComplete="organization"
          hint="The company you bill for. You can add GST details later."
          error={errors.business_name?.message}
          registration={form.register("business_name")}
        />
        <TextField
          id="email"
          label="Email"
          type="email"
          autoComplete="username"
          error={errors.email?.message}
          registration={form.register("email")}
        />
        <TextField
          id="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters. A few unrelated words work well."
          error={errors.password?.message}
          registration={form.register("password")}
        />
        <Button type="submit" disabled={form.formState.isSubmitting}>
          Create account
        </Button>
      </form>
      <p className="text-muted-foreground text-sm">
        Already have an account?{" "}
        <Link to="/login" className="text-foreground underline">
          Sign in
        </Link>
      </p>
    </AuthCard>
  );
}
