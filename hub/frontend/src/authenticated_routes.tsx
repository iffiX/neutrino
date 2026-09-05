import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/app_shell";
import { Icon } from "./components/icon";
import { AiPage } from "./pages/ai_page";
import { ContainersPage } from "./pages/containers_page";
import { DashboardPage } from "./pages/dashboard_page";
import { DevicesPage } from "./pages/devices_page";
import { GiteaPage } from "./pages/gitea_page";
import { CredentialsPage } from "./pages/credentials_page";
import { LoginPage } from "./pages/login_page";
import { NetbirdPage } from "./pages/netbird_page";
import { NetworkPage } from "./pages/network_page";
import { NotFoundPage } from "./pages/not_found_page";
import { ProxyPage } from "./pages/proxy_page";
import { SambaPage } from "./pages/samba_page";
import { ModulesPage } from "./pages/modules_page";
import { ServicesPage } from "./pages/services_page";
import { SettingsPage } from "./pages/settings_page";
import { ZfsPage } from "./pages/zfs_page";
import { useAuth } from "./use_auth";

import "./app.css";

/**
 * The session gate and the route table behind it.
 *
 * Authentication is a whole-app switch rather than a per-route guard because
 * the panel has exactly one credential and nothing worth showing without it.
 * A 401 from anywhere flips `isAuthenticated` through the auth provider, so an
 * expired session lands on the login card from whichever page was open.
 */
export function AuthenticatedRoutes() {
  const { isAuthenticated, isChecking } = useAuth();

  if (isChecking) {
    return (
      <div className="app_splash">
        <div className="app_splash_inner">
          <span className="app_splash_mark">
            <Icon name="proxy" size={22} />
          </span>
          <span className="app_splash_text">checking session…</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="network" element={<NetworkPage />} />
        <Route path="proxy" element={<ProxyPage />} />
        <Route path="netbird" element={<NetbirdPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="credentials" element={<CredentialsPage />} />
        {/* The page's old address, kept so bookmarks from when it was called
            Keys still land somewhere sensible. */}
        <Route path="keys" element={<CredentialsPage />} />
        <Route path="modules" element={<ModulesPage />} />
        <Route path="services" element={<ServicesPage />} />
        <Route path="settings" element={<SettingsPage />} />
        {/* The Terminal renders nothing here: the shell keeps it mounted
            beside the outlet so its sessions survive navigation. */}
        <Route path="terminal" element={null} />
        {/* Optional pages are routed whether or not their service is on. The
            sidebar decides what is worth offering; a bookmark to a page whose
            service was switched off should still open. */}
        <Route path="samba" element={<SambaPage />} />
        <Route path="containers" element={<ContainersPage />} />
        <Route path="gitea" element={<GiteaPage />} />
        <Route path="zfs" element={<ZfsPage />} />
        <Route path="ai" element={<AiPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
