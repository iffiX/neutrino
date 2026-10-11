/**
 * What the Modules page knows of each program run as a person's account,
 * keyed by module name: the hub's description table as the panel reads it.
 *
 * One `instances_panel.tsx` draws every such module. What differs between
 * them is here: the words each speaks with, the port a first instance is
 * offered, whether a Windows machine runs each instance with a login, and
 * whether the machine reports `installing` before any instance can run.
 */

/** The catalog keys one module's instances panel speaks with. */
export interface InstancesWording {
  instancesTitle: string;
  instancesHint: string;
  add: string;
  empty: string;
  account: string;
  accountPlaceholder: string;
  port: string;
  running: string;
  stopped: string;
  remove: string;
  apply: string;
  applyHint: string;
  /** The Windows login picker's label, with `{account}`, and the line under
   * it; absent for a module whose instances name no login. */
  login?: string;
  loginHint?: string;
  /** The line above the instances saying the owner installs the software,
   * and the same once the machine reports the installed `{version}`. */
  ownerNotice?: string;
  ownerNoticeVersion?: string;
}

export interface ModuleDescriptor {
  /** The module's manifest name. */
  name: string;
  /** The port a first instance is offered; the next is the one after the
   * highest in use. */
  firstPort: number;
  /** Whether each instance names a vault login, which a Windows machine
   * runs it as. */
  isLoginNamed: boolean;
  /** Whether an instance reads `installing` while the machine reports the
   * module installing, before any instance can run. */
  isInstallingShown: boolean;
  wording: InstancesWording;
}

export const MODULE_DESCRIPTORS: Record<string, ModuleDescriptor> = {
  vscode: {
    name: "vscode",
    firstPort: 8000,
    isLoginNamed: true,
    isInstallingShown: false,
    wording: {
      instancesTitle: "ui.vscode.instances_title",
      instancesHint: "ui.vscode.instances_hint",
      add: "ui.vscode.add",
      empty: "ui.vscode.empty",
      account: "ui.vscode.account",
      accountPlaceholder: "ui.vscode.account_placeholder",
      port: "ui.vscode.port",
      running: "ui.vscode.running",
      stopped: "ui.vscode.stopped",
      remove: "ui.vscode.remove",
      apply: "ui.vscode.apply",
      applyHint: "ui.vscode.apply_hint",
      login: "ui.vscode.login",
      loginHint: "ui.vscode.login_hint",
    },
  },
  code_server: {
    name: "code_server",
    firstPort: 8443,
    isLoginNamed: false,
    isInstallingShown: false,
    wording: {
      instancesTitle: "ui.code_server.instances_title",
      instancesHint: "ui.code_server.instances_hint",
      add: "ui.code_server.add",
      empty: "ui.code_server.empty",
      account: "ui.code_server.account",
      accountPlaceholder: "ui.code_server.account_placeholder",
      port: "ui.code_server.port",
      running: "ui.code_server.running",
      stopped: "ui.code_server.stopped",
      remove: "ui.code_server.remove",
      apply: "ui.code_server.apply",
      applyHint: "ui.code_server.apply_hint",
      ownerNotice: "ui.code_server.owner_notice",
      ownerNoticeVersion: "ui.code_server.owner_notice_version",
    },
  },
  cloudcli: {
    name: "cloudcli",
    firstPort: 3001,
    isLoginNamed: true,
    isInstallingShown: true,
    wording: {
      instancesTitle: "ui.cloudcli.instances_title",
      instancesHint: "ui.cloudcli.instances_hint",
      add: "ui.cloudcli.add",
      empty: "ui.cloudcli.empty",
      account: "ui.cloudcli.account",
      accountPlaceholder: "ui.cloudcli.account_placeholder",
      port: "ui.cloudcli.port",
      running: "ui.cloudcli.running",
      stopped: "ui.cloudcli.stopped",
      remove: "ui.cloudcli.remove",
      apply: "ui.cloudcli.apply",
      applyHint: "ui.cloudcli.apply_hint",
      login: "ui.cloudcli.login",
      loginHint: "ui.cloudcli.login_hint",
    },
  },
};
