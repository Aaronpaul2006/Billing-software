import { ApiError } from "@/api/problem";

/** What the user can do about an error, in plain words. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "Your role does not have access to this.";
    if (error.status === 404)
      return "Not found. It may have been removed, or belong to another company.";
    if (error.status === 0) return "Could not reach the server. Check your connection.";
    if (error.status >= 500) return "Something went wrong on our side. Try again in a moment.";
    return error.message;
  }
  return "Could not reach the server. Check your connection.";
}
