import { BrowserRouter } from "react-router-dom";

import { AuthenticatedRoutes } from "./authenticated_routes";
import { AuthProvider } from "./auth_provider";

/**
 * The application root.
 *
 * It exists only to nest the two providers every page depends on — routing
 * outside auth, so the login card can still read the current location — and
 * hand off to the route table.
 */
export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AuthenticatedRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
