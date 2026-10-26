import { Outlet } from "react-router-dom";

import { BottomNav } from "./bottom_nav";
import { SidebarNav } from "./sidebar_nav";
import { TopBar } from "./top_bar";
import { StatsContext } from "../stats_context";
import { useAuth } from "../use_auth";
import { useHubEventChannel } from "../use_hub_events";
import { useStatsSocket } from "../use_stats_socket";

import "./app_shell.css";

/**
 * The authenticated layout: fixed rail — a bottom bar on narrow and portrait
 * viewports — status bar, routed body.
 *
 * The window's height is divided up here rather than grown into: the body is
 * what scrolls, so the bar above it stays put.
 *
 * The shell owns the one live stats socket and publishes it, so the top bar
 * and the dashboard read identical frames from a single connection. It opens
 * the panel's one event socket beside it: every page refetches what it draws
 * from what arrives there, and nothing polls. The two blurred glows behind
 * the content are the only decorative elements in the app, and they stand
 * still: a moving blur is repainted every frame on a machine without a GPU.
 */

export function AppShell() {
  const { logout } = useAuth();
  const stats = useStatsSocket();
  useHubEventChannel();

  const handleLogout = () => {
    void logout();
  };

  return (
    <StatsContext.Provider value={stats}>
      <div className="app_shell">
        <div className="app_shell_glow app_shell_glow--cyan" />
        <div className="app_shell_glow app_shell_glow--violet" />
        <SidebarNav onLogout={handleLogout} />
        <div className="app_shell_main">
          <TopBar />
          <main className="app_shell_body">
            <div className="app_shell_content">
              <Outlet />
            </div>
          </main>
        </div>
        <BottomNav onLogout={handleLogout} />
      </div>
    </StatsContext.Provider>
  );
}
