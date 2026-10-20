import { Navigate, Outlet, useLocation } from "react-router";

import { FullPageSpinner } from "@/components/FullPageSpinner";

import { useAuth } from "./context";

/** Routes behind sign-in. OWNER / ADMIN without MFA must enrol first. */
export function RequireAuth({ enrolment = false }: { enrolment?: boolean }) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <FullPageSpinner />;
  if (state.status === "signed_out") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  const mustEnrol = state.session.mfa_enrollment_required;
  if (mustEnrol && !enrolment) return <Navigate to="/mfa/setup" replace />;
  if (!mustEnrol && enrolment) return <Navigate to="/" replace />;
  return <Outlet />;
}
