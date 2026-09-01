import { useEffect, useState } from "react";
import { BrowserRouter } from "react-router-dom";

import { AuthenticatedRoutes } from "./authenticated_routes";
import { AuthProvider } from "./auth_provider";
import { SetupPage, SetupTokenMissing } from "./pages/setup_page";
import type { SetupContext } from "./setup_api";
import { isSetupWaiting, readSetupContext, setupToken } from "./setup_api";

/**
 * The application root.
 *
 * Usually it exists only to nest the two providers every page depends on —
 * routing outside auth, so the login card can still read the current location
 * — and hand off to the route table.
 *
 * Before there is a panel there is no session to provide: `nhub setup` serves
 * this same bundle on a one-time token while it waits for the first run to be
 * answered in a browser. Which of the two is serving is asked of the server
 * rather than read off the address, because a link that has lost its token is
 * exactly the case where the address says nothing — and drawing the panel's
 * login card over a box that has no panel is how that ends up looking like a
 * broken API rather than a missing link.
 */
type Showing = "checking" | "panel" | "wizard" | "needs_token";

export function App() {
  const token = setupToken();
  const [context, setContext] = useState<SetupContext | null>(null);
  const [showing, setShowing] = useState<Showing>("checking");

  useEffect(() => {
    let isCancelled = false;
    void (async () => {
      if (!(await isSetupWaiting())) {
        if (!isCancelled) {
          setShowing("panel");
        }
        return;
      }
      if (token === "") {
        if (!isCancelled) {
          setShowing("needs_token");
        }
        return;
      }
      try {
        const answer = await readSetupContext(token);
        if (!isCancelled) {
          setContext(answer);
          setShowing("wizard");
        }
      } catch {
        // The server is the wizard's, so the token is the thing that is
        // wrong: stale, mistyped, or from a run that has since ended.
        if (!isCancelled) {
          setShowing("needs_token");
        }
      }
    })();
    return () => {
      isCancelled = true;
    };
  }, [token]);

  if (showing === "checking") {
    return null;
  }
  if (showing === "needs_token") {
    return <SetupTokenMissing />;
  }
  if (showing === "wizard" && context !== null) {
    return <SetupPage token={token} context={context} />;
  }
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuthenticatedRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
