import { ApiError } from "@/api/problem";

/** What the user can do about an error, in plain words. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "email_not_verified")
      return "Confirm your email address first: open the link we emailed you, or send a new one from the banner at the top.";
    if (error.status === 403) return "Your role does not have access to this.";
    if (error.status === 404)
      return "Not found. It may have been removed, or belong to another company.";
    if (error.status === 0) return "Could not reach the server. Check your connection.";
    if (error.status >= 500) return "Something went wrong on our side. Try again in a moment.";
    return error.message;
  }
  return "Could not reach the server. Check your connection.";
}

/** Why an emailed link (verify email, reset password) did not work; null for other errors. */
export function linkError(error: unknown): string | null {
  const code = error instanceof ApiError ? error.problem.errors?.[0]?.code : undefined;
  if (code === "link_expired") return "This link has expired.";
  if (code === "link_invalid") return "This link has already been used or is not valid.";
  return null;
}
