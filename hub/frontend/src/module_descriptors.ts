/**
 * The modules of the account layer, as the machine page draws their tabs:
 * the hub's description table as the panel reads it, keyed by module name.
 *
 * One `instances_panel.tsx` draws each tab's **Enabled accounts**. What
 * differs between them is here: the apply bar's words, the account's own
 * field a row shows beside its name, and the line saying the owner installs
 * the software.
 */

/** The account's field a module's row shows beside the account's name. */
export type AccountField = "shell_path" | "share_path";

export interface ModuleDescriptor {
  /** The module's manifest name. */
  name: string;
  /** The apply bar's label and hint. */
  apply: string;
  applyHint: string;
  /** The account's field each row shows; none for most modules. */
  field: AccountField | null;
  /** The line above the accounts saying the owner installs the software,
   * and the same once the machine reports the installed `{version}`. */
  ownerNotice?: string;
  ownerNoticeVersion?: string;
}

export const MODULE_DESCRIPTORS: Record<string, ModuleDescriptor> = {
  samba: {
    name: "samba",
    apply: "ui.samba.apply",
    applyHint: "ui.samba.apply_hint",
    field: "share_path",
  },
  terminal: {
    name: "terminal",
    apply: "ui.terminal_module.apply",
    applyHint: "ui.terminal_module.apply_hint",
    field: "shell_path",
  },
  ssh_server: {
    name: "ssh_server",
    apply: "ui.ssh_server.apply",
    applyHint: "ui.ssh_server.apply_hint",
    field: null,
  },
  vscode: {
    name: "vscode",
    apply: "ui.vscode.apply",
    applyHint: "ui.vscode.apply_hint",
    field: null,
  },
  code_server: {
    name: "code_server",
    apply: "ui.code_server.apply",
    applyHint: "ui.code_server.apply_hint",
    field: null,
    ownerNotice: "ui.code_server.owner_notice",
    ownerNoticeVersion: "ui.code_server.owner_notice_version",
  },
  cloudcli: {
    name: "cloudcli",
    apply: "ui.cloudcli.apply",
    applyHint: "ui.cloudcli.apply_hint",
    field: null,
  },
  codeg: {
    name: "codeg",
    apply: "ui.codeg.apply",
    applyHint: "ui.codeg.apply_hint",
    field: null,
  },
  siyuan: {
    name: "siyuan",
    apply: "ui.siyuan.apply",
    applyHint: "ui.siyuan.apply_hint",
    field: null,
  },
};
