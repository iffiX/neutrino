import { useEffect, useState } from "react";
import { BrowserRouter } from "react-router-dom";

import { AuthenticatedRoutes } from "./authenticated_routes";
import { AuthProvider } from "./auth_provider";
import { SetupPage } from "./pages/setup_page";
import type { SetupContext } from "./setup_api";
import { readSetupContext, setupToken } from "./setup_api";

/**
 * The application root.
 *
 * Usually it exists only to nest the two providers every page depends on —
 * routing outside auth, so the login card can still read the current location
 * — and hand off to the route table.
 *
 * Before there is a panel there is no session to provide: `nhub setup` serves
 * this same bundle on a one-time token while it waits for the first run to be
 * answered in a browser. A token in the address is what says so, and it is
 * checked against the server rather than believed, so a link kept in somebody's
 * history opens the panel it now points at.
 */
export function App() {
  const token = setupToken();
  const [context, setContext] = useState<SetupContext | null>(null);
  const [isChecked, setIsChecked] = useState(token === "");

  useEffect(() => {
    if (token === "") {
      return;
    }
    let isCancelled = false;
    readSetupContext(token)
      .then((answer) => !isCancelled && setContext(answer))
      .catch(() => {
        // Not a box waiting to be set up, so this is the panel.
      })
      .finally(() => !isCancelled && setIsChecked(true));
    return () => {
      isCancelled = true;
    };
  }, [token]);

  if (!isChecked) {
    return null;
  }
  if (context !== null) {
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
