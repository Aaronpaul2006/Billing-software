import { Navigate, Outlet, useLocation } from "react-router";

import { FullPageSpinner } from "@/components/FullPageSpinner";

import { useAuth } from "./context";

/**
 * Routes behind sign-in. OWNER / ADMIN without MFA must enrol first. People
 * at a client (role CLIENT) only have the client portal (`portal` routes),
 * and the business's own people never see it.
 */
export function RequireAuth({
  enrolment = false,
  portal = false,
}: {
  enrolment?: boolean;
  portal?: boolean;
}) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <FullPageSpinner />;
  if (state.status === "signed_out") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  const isClient = state.session.role === "CLIENT";
  if (isClient && !portal) return <Navigate to="/portal" replace />;
  if (!isClient && portal) return <Navigate to="/" replace />;
  const mustEnrol = state.session.mfa_enrollment_required;
  if (mustEnrol && !enrolment) return <Navigate to="/mfa/setup" replace />;
  if (!mustEnrol && enrolment) return <Navigate to="/" replace />;
  return <Outlet />;
}
