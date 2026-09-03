import { Outlet, useLocation } from "react-router-dom";

import { TerminalPage } from "../pages/terminal_page";
import { BottomNav } from "./bottom_nav";
import { SidebarNav } from "./sidebar_nav";
import { TopBar } from "./top_bar";
import { ServicesContext } from "../services_context";
import { StatsContext } from "../stats_context";
import { useApiResource } from "../use_api_resource";
import { useAuth } from "../use_auth";
import { useStatsSocket } from "../use_stats_socket";
import type { ServicesResponse } from "../api_types";

import "./app_shell.css";

/**
 * The authenticated layout: fixed rail — a bottom bar on narrow and portrait
 * viewports — status bar, routed body.
 *
 * The window's height is divided up here rather than grown into: the body is
 * what scrolls, so the bar above it stays put and a page can ask to fill
 * exactly what is left — which the Terminal does, and which a page cannot do
 * against a container that would just get taller to accommodate it.
 *
 * The shell owns the one live stats socket and publishes it, so the top bar
 * and the dashboard read identical frames from a single connection. The two
 * blurred glows behind the content are the only decorative elements in the
 * app; they drift slowly enough to read as depth rather than motion.
 */

export function AppShell() {
  const { logout } = useAuth();
  // The Terminal is not routed like the other pages: it stays mounted here
  // and is merely hidden while another page shows. Unmounting it would close
  // every shell's socket, and open shells are exactly what a person expects
  // to find again after looking something up on another tab.
  const isTerminalOpen = useLocation().pathname === "/terminal";
  const stats = useStatsSocket();
  // One copy of the service list for the whole shell: the sidebar reads it to
  // decide which optional pages exist, and the Services page writes each
  // action's result back into it, so disabling a service drops its page from
  // the rail in the same render.
  const services = useApiResource<ServicesResponse>("/services");

  const handleLogout = () => {
    void logout();
  };

  return (
    <StatsContext.Provider value={stats}>
      <ServicesContext.Provider value={services}>
        <div className="app_shell">
          <div className="app_shell_glow app_shell_glow--cyan" />
          <div className="app_shell_glow app_shell_glow--violet" />
          <SidebarNav onLogout={handleLogout} />
          <div className="app_shell_main">
            <TopBar />
            <main className="app_shell_body">
              <div className="app_shell_content">
                <Outlet />
                <div
                  className={`app_shell_terminal ${
                    isTerminalOpen ? "" : "app_shell_terminal--hidden"
                  }`}
                >
                  <TerminalPage />
                </div>
              </div>
            </main>
          </div>
          <BottomNav onLogout={handleLogout} />
        </div>
      </ServicesContext.Provider>
    </StatsContext.Provider>
  );
}
