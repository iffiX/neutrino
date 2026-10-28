import type { PermissionValue } from "./components/client_permission_form";
import type { ClientListView, ClientView } from "./api_types";

/**
 * The permissions of the Clients page as the permission form reads them.
 */

/** The default permission. */
export function defaultPermissionOf(listView: ClientListView): PermissionValue {
  return {
    kinds: listView.default_permission,
    devices: listView.default_permission_devices,
    entries: listView.default_permission_entries,
  };
}

/** A client's own permission; null while it follows the default. */
export function clientPermissionOf(client: ClientView): PermissionValue | null {
  if (client.permission === null) {
    return null;
  }
  return {
    kinds: client.permission,
    devices: client.permission_devices,
    entries: client.permission_entries,
  };
}
