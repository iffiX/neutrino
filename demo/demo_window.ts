import type { DemoClientCore } from "./demo_client_core";
import type { DemoHub } from "./demo_hub";

/**
 * The page's top window, as the two frames reach it. They share its one fake
 * hub and its client core.
 */
export interface DemoWindow extends Window {
  neutrinoDemoHub: DemoHub;
  neutrinoDemoClient: DemoClientCore;
  /** Turns the phone for the viewer page, and back. */
  neutrinoDemoViewerFrame: (isOpen: boolean) => void;
}

/** A panel frame, as the top window reaches it. */
export interface DemoPanelWindow extends Window {
  /** Ends the panel's tree, and with it the frame's sockets and listeners. */
  neutrinoDemoPanelStop?: () => void;
}
