import { useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { ZfsTopology } from "./zfs_topology";
import { apiDelete, apiPost, describeError } from "../api_client";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_DEVICE_REPORT } from "../use_hub_events";
import { useConfirm } from "../use_confirm";
import type { ZfsDataset, ZfsDeviceView, ZfsDisk } from "../api_types";

import "./samba_panels.css";
import "./zfs_panels.css";

/**
 * Storage on one machine: the topology, the pools, the datasets.
 *
 * There is no draft-and-apply here — a pool's truth is on its disks, so these
 * panels are a live viewport with guarded verbs. The dangerous ones ask
 * properly: wiping disks and destroying pools want words typed back, exactly
 * as uninstalling a module does.
 */

const LAYOUTS: {
  value: string;
  labelKey: string;
  minimum: number;
  hintKey: string;
}[] = [
  {
    value: "single",
    labelKey: "ui.zfs.layout_single",
    minimum: 1,
    hintKey: "ui.zfs.layout_single_hint",
  },
  {
    value: "mirror",
    labelKey: "ui.zfs.layout_mirror",
    minimum: 2,
    hintKey: "ui.zfs.layout_mirror_hint",
  },
  {
    value: "raidz1",
    labelKey: "ui.zfs.layout_raidz1",
    minimum: 3,
    hintKey: "ui.zfs.layout_raidz1_hint",
  },
  {
    value: "raidz2",
    labelKey: "ui.zfs.layout_raidz2",
    minimum: 4,
    hintKey: "ui.zfs.layout_raidz2_hint",
  },
];

const COMPRESSIONS = ["lz4", "zstd", "off"];
const RECORDSIZES = ["16K", "32K", "64K", "128K", "256K", "512K", "1M"];

interface Builder {
  target: "new" | string;
  name: string;
  layout: string;
  devices: string[];
  wipeText: string;
}

interface ZfsPanelsProps {
  /** The machine whose pools these are. */
  deviceId: string;
  /** Where this machine's ZFS answers. */
  basePath: string;
  isEditable: boolean;
}

export function ZfsPanels({ deviceId, basePath, isEditable }: ZfsPanelsProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  // Resilvers and scrubs move on their own, which the machine's own report
  // says; the datasets are a write like any other.
  const zfs = useApiResource<ZfsDeviceView>(basePath, {
    invalidateOn: [
      { type: HUB_EVENT_DEVICE_REPORT, key: deviceId },
      { type: HUB_EVENT_CONFIG },
    ],
  });

  const [selectedMember, setSelectedMember] = useState<{
    pool: string;
    device: string;
  } | null>(null);
  const [replaceWith, setReplaceWith] = useState<string | null>(null);
  const [isReplacing, setIsReplacing] = useState(false);
  const [builder, setBuilder] = useState<Builder | null>(null);
  const [destroyConfirm, setDestroyConfirm] = useState<{
    pool: string;
    text: string;
  } | null>(null);
  const [isDatasetCreatorOpen, setIsDatasetCreatorOpen] = useState(false);
  const [datasetDraft, setDatasetDraft] = useState({
    pool: "",
    name: "",
    mountpoint: "",
    compression: "lz4",
    recordsize: "128K",
  });
  const [shareTarget, setShareTarget] = useState<ZfsDataset | null>(null);
  const confirm = useConfirm();
  const [isBusy, setIsBusy] = useState(false);
  // Errors surface beside the control that caused them, keyed by scope.
  const [actionError, setActionError] = useState<{
    scope: string;
    message: string;
  } | null>(null);

  const view = zfs.data;

  const act = async (scope: string, work: () => Promise<ZfsDeviceView>) => {
    if (!isEditable) {
      setActionError({ scope, message: t("ui.modules.agent_offline") });
      return false;
    }
    setIsBusy(true);
    setActionError(null);
    try {
      zfs.setData(await work());
      return true;
    } catch (cause: unknown) {
      setActionError({ scope, message: describeError(cause) });
      return false;
    } finally {
      setIsBusy(false);
    }
  };

  const errorFor = (scope: string): string | null =>
    actionError !== null && actionError.scope === scope
      ? actionError.message
      : null;

  const availableDisks = useMemo(
    () => (view?.disks ?? []).filter((disk) => disk.is_available),
    [view],
  );
  const memberDisk = useMemo(() => {
    if (view === null || selectedMember === null) {
      return null;
    }
    return (
      view.disks.find((disk) => {
        const byId = disk.by_id.split("/").pop();
        const device = disk.device.split("/").pop();
        return (
          byId === selectedMember.device || device === selectedMember.device
        );
      }) ?? null
    );
  }, [view, selectedMember]);
  const member = useMemo(() => {
    if (view === null || selectedMember === null) {
      return null;
    }
    for (const pool of view.pools) {
      if (pool.name !== selectedMember.pool) {
        continue;
      }
      for (const vdev of pool.vdevs) {
        for (const candidate of vdev.members) {
          if (candidate.name === selectedMember.device) {
            return candidate;
          }
        }
      }
    }
    return null;
  }, [view, selectedMember]);

  if (zfs.error !== null && view === null) {
    return <ErrorPanel message={zfs.error} onRetry={zfs.reload} />;
  }
  if (view === null) {
    return <div className="skeleton" style={{ height: 240 }} />;
  }
  if (!view.is_installed) {
    return (
      <div className="placeholder">
        <span>{t("ui.zfs.not_installed")}</span>
        <span className="faint">{t("ui.zfs.not_installed_hint")}</span>
      </div>
    );
  }

  const openBuilder = (target: "new" | string) => {
    setBuilder({
      target,
      name: "",
      layout: "single",
      devices: [],
      wipeText: "",
    });
    setActionError(null);
  };

  const builderDisks = availableDisks.filter((disk) =>
    builder?.devices.includes(disk.by_id),
  );
  const isWipeNeeded = builderDisks.some((disk) => disk.fstype.length > 0);
  const isBuilderReady =
    builder !== null &&
    builder.devices.length >=
      (LAYOUTS.find((layout) => layout.value === builder.layout)?.minimum ??
        1) &&
    (builder.layout !== "single" || builder.devices.length === 1) &&
    (builder.target !== "new" || builder.name.trim().length > 0) &&
    (!isWipeNeeded || builder.wipeText === "wipe");

  const submitBuilder = async (isForced = false) => {
    if (builder === null || !isBuilderReady) {
      return;
    }
    const body = {
      layout: builder.layout,
      devices: builder.devices,
      is_forced: isWipeNeeded || isForced,
    };
    const isDone = await act("builder", () =>
      builder.target === "new"
        ? apiPost<ZfsDeviceView>(`${basePath}/pools`, {
            ...body,
            name: builder.name.trim(),
          })
        : apiPost<ZfsDeviceView>(
            `${basePath}/pools/${builder.target}/expand`,
            body,
          ),
    );
    if (isDone) {
      setBuilder(null);
    }
  };

  const submitReplace = async () => {
    if (selectedMember === null || replaceWith === null) {
      return;
    }
    const isDone = await act("member", () =>
      apiPost<ZfsDeviceView>(
        `${basePath}/pools/${selectedMember.pool}/replace`,
        {
          old_device: selectedMember.device,
          new_device: replaceWith,
        },
      ),
    );
    if (isDone) {
      setIsReplacing(false);
      setReplaceWith(null);
      setSelectedMember(null);
    }
  };

  const submitDatasetCreate = async () => {
    const pool = datasetDraft.pool || view.pools[0]?.name;
    if (!pool || datasetDraft.name.trim().length === 0) {
      return;
    }
    const isDone = await act("datasets", () =>
      apiPost<ZfsDeviceView>(`${basePath}/datasets`, {
        pool,
        name: datasetDraft.name.trim(),
        compression: datasetDraft.compression,
        recordsize: datasetDraft.recordsize,
        mountpoint:
          datasetDraft.mountpoint.trim().length > 0
            ? datasetDraft.mountpoint.trim()
            : null,
      }),
    );
    if (isDone) {
      setDatasetDraft({
        pool: "",
        name: "",
        mountpoint: "",
        compression: "lz4",
        recordsize: "128K",
      });
      setIsDatasetCreatorOpen(false);
    }
  };

  return (
    <>
      {view.importable.map((candidate) => (
        <div className="notice" key={candidate.name}>
          <Icon name="database" size={15} />
          <div className="notice_body">
            {t("ui.zfs.import_found", {
              name: candidate.name,
              state: candidate.state.toLowerCase(),
            })}
          </div>
          <button
            type="button"
            className="button button--small"
            onClick={() =>
              void act("import", () =>
                apiPost<ZfsDeviceView>(`${basePath}/import/${candidate.name}`),
              )
            }
            disabled={isBusy}
          >
            {t("ui.zfs.import")}
          </button>
        </div>
      ))}

      {errorFor("import") !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{errorFor("import")}</div>
        </div>
      )}

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.zfs.topology_title")}</h2>
        </div>
        <ZfsTopology
          pools={view.pools}
          disks={view.disks}
          selectedMember={selectedMember}
          onSelectMember={(pool, device) => {
            setSelectedMember(
              selectedMember?.device === device ? null : { pool, device },
            );
            setIsReplacing(false);
            setReplaceWith(null);
          }}
        />

        {selectedMember !== null && member !== null && (
          <div className="zfs_member_panel">
            <div className="zfs_member_actions">
              <span className="mono">{selectedMember.device}</span>
              <span className="zfs_member_actions_state">
                {member.state.toLowerCase()}
              </span>
              <span className="zfs_member_actions_spacer" />
              {!isReplacing && (
                <>
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => setIsReplacing(true)}
                    disabled={isBusy || availableDisks.length === 0}
                    title={
                      availableDisks.length === 0
                        ? t("ui.zfs.no_spare_replace")
                        : undefined
                    }
                  >
                    {t("ui.zfs.replace")}
                  </button>
                  {member.state === "OFFLINE" ? (
                    <button
                      type="button"
                      className="button button--small"
                      onClick={() =>
                        void act("member", () =>
                          apiPost<ZfsDeviceView>(
                            `${basePath}/pools/${selectedMember.pool}/online`,
                            { device: selectedMember.device },
                          ),
                        )
                      }
                      disabled={isBusy}
                    >
                      {t("ui.zfs.online")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button button--small"
                      onClick={() =>
                        void act("member", () =>
                          apiPost<ZfsDeviceView>(
                            `${basePath}/pools/${selectedMember.pool}/offline`,
                            { device: selectedMember.device },
                          ),
                        )
                      }
                      disabled={isBusy}
                    >
                      {t("ui.zfs.offline")}
                    </button>
                  )}
                </>
              )}
              {isReplacing && (
                <>
                  <select
                    className="select zfs_replace_select"
                    value={replaceWith ?? ""}
                    onChange={(event) =>
                      setReplaceWith(event.target.value || null)
                    }
                  >
                    <option value="">{t("ui.zfs.replacement_pick")}</option>
                    {availableDisks.map((disk) => (
                      <option key={disk.by_id} value={disk.by_id}>
                        {shortId(disk)} · {formatBytes(disk.size_bytes)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() => void submitReplace()}
                    disabled={isBusy || replaceWith === null}
                  >
                    {t("ui.zfs.start_resilver")}
                  </button>
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    onClick={() => {
                      setIsReplacing(false);
                      setReplaceWith(null);
                    }}
                  >
                    {t("ui.zfs.cancel")}
                  </button>
                </>
              )}
            </div>
            <dl className="zfs_member_details">
              {memberDetailRows(member, memberDisk).map(([label, value]) => (
                <div className="zfs_member_detail" key={label}>
                  <dt>{label}</dt>
                  <dd className="mono">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
        {errorFor("member") !== null && (
          <div className="notice notice--error">
            <Icon name="alert" size={15} />
            <div className="notice_body">{errorFor("member")}</div>
          </div>
        )}
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.zfs.pools_title")}</h2>
        </div>
        {view.pools.length === 0 ? (
          <div className="placeholder">
            <span>{t("ui.zfs.pools_empty")}</span>
            <span className="faint">{t("ui.zfs.pools_empty_hint")}</span>
          </div>
        ) : (
          view.pools.map((pool) => (
            <div className="zfs_pool_card" key={pool.name}>
              <div className="zfs_pool_row">
                <span className="zfs_pool_title mono">{pool.name}</span>
                <span
                  className={`badge ${
                    pool.state === "ONLINE"
                      ? "badge--ok"
                      : pool.state === "DEGRADED"
                        ? "badge--warn"
                        : "badge--error"
                  }`}
                >
                  {pool.state.toLowerCase()}
                </span>
                {pool.capacity_percent >= 80 && (
                  <span className="badge badge--warn">
                    {t("ui.zfs.capacity_full", {
                      percent: pool.capacity_percent,
                    })}
                  </span>
                )}
                <span className="zfs_pool_numbers">
                  {t("ui.zfs.pool_numbers", {
                    allocated: formatBytes(pool.allocated_bytes),
                    size: formatBytes(pool.size_bytes),
                    frag: pool.fragmentation_percent,
                  })}
                </span>
                <span className="zfs_member_actions_spacer" />
                {pool.scan.kind !== null ? (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() =>
                      void act(`pool:${pool.name}`, () =>
                        apiPost<ZfsDeviceView>(
                          `${basePath}/pools/${pool.name}/scrub/stop`,
                        ),
                      )
                    }
                    disabled={isBusy}
                  >
                    {t("ui.zfs.stop_scan", { kind: pool.scan.kind })}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() =>
                      void act(`pool:${pool.name}`, () =>
                        apiPost<ZfsDeviceView>(
                          `${basePath}/pools/${pool.name}/scrub`,
                        ),
                      )
                    }
                    disabled={isBusy}
                  >
                    {t("ui.zfs.scrub")}
                  </button>
                )}
                <button
                  type="button"
                  className="button button--small"
                  onClick={() => openBuilder(pool.name)}
                  disabled={isBusy || availableDisks.length === 0}
                  title={
                    availableDisks.length === 0
                      ? t("ui.zfs.no_spare_grow")
                      : undefined
                  }
                >
                  {t("ui.zfs.expand")}
                </button>
                <button
                  type="button"
                  className="button button--ghost button--small"
                  onClick={() =>
                    setDestroyConfirm(
                      destroyConfirm?.pool === pool.name
                        ? null
                        : { pool: pool.name, text: "" },
                    )
                  }
                  disabled={isBusy}
                >
                  <Icon name="trash" size={13} />
                </button>
              </div>

              <div className="zfs_pool_meta">
                {pool.scan.kind !== null ? (
                  <span>
                    {pool.scan.eta === null
                      ? t("ui.zfs.scan_progress", {
                          kind: pool.scan.kind,
                          percent: pool.scan.percent?.toFixed(1) ?? "?",
                        })
                      : t("ui.zfs.scan_progress_eta", {
                          kind: pool.scan.kind,
                          percent: pool.scan.percent?.toFixed(1) ?? "?",
                          eta: pool.scan.eta,
                        })}
                  </span>
                ) : (
                  pool.scan.summary && <span>{pool.scan.summary}</span>
                )}
                {pool.errors && (
                  <span className="zfs_pool_errors">{pool.errors}</span>
                )}
              </div>

              {errorFor(`pool:${pool.name}`) !== null && (
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {errorFor(`pool:${pool.name}`)}
                  </div>
                </div>
              )}

              {destroyConfirm?.pool === pool.name && (
                <div className="zfs_destroy_confirm">
                  <span>
                    {t("ui.zfs.destroy_warning", { name: pool.name })}
                  </span>
                  <input
                    className="input"
                    value={destroyConfirm.text}
                    placeholder={pool.name}
                    onChange={(event) =>
                      setDestroyConfirm({
                        pool: pool.name,
                        text: event.target.value,
                      })
                    }
                  />
                  <button
                    type="button"
                    className="button button--danger button--small"
                    disabled={isBusy || destroyConfirm.text !== pool.name}
                    onClick={() =>
                      void act(`pool:${pool.name}`, () =>
                        apiDelete<ZfsDeviceView>(
                          `${basePath}/pools/${pool.name}`,
                        ),
                      ).then((isDone) => {
                        if (isDone) {
                          setDestroyConfirm(null);
                        }
                      })
                    }
                  >
                    {t("ui.zfs.destroy_pool")}
                  </button>
                </div>
              )}
            </div>
          ))
        )}

        {builder !== null && (
          <div className="zfs_builder">
            <div className="zfs_builder_head">
              <h3>
                {builder.target === "new"
                  ? t("ui.zfs.create_pool")
                  : t("ui.zfs.expand_pool", { name: builder.target })}
              </h3>
            </div>
            {builder.target !== "new" && (
              <p className="field_hint">{t("ui.zfs.expand_note")}</p>
            )}

            {builder.target === "new" && (
              <label className="field zfs_builder_name">
                <span className="field_label">{t("ui.zfs.pool_name")}</span>
                <input
                  className="input"
                  value={builder.name}
                  placeholder="tank"
                  onChange={(event) =>
                    setBuilder({ ...builder, name: event.target.value })
                  }
                />
              </label>
            )}

            <div className="zfs_builder_disks">
              <span className="section_label">
                {builder.target === "new"
                  ? t("ui.zfs.first_vdev_disks")
                  : t("ui.zfs.new_vdev_disks")}
              </span>
              {availableDisks.map((disk) => (
                <label className="zfs_builder_disk" key={disk.by_id}>
                  <input
                    type="checkbox"
                    checked={builder.devices.includes(disk.by_id)}
                    onChange={(event) =>
                      setBuilder({
                        ...builder,
                        devices: event.target.checked
                          ? [...builder.devices, disk.by_id]
                          : builder.devices.filter((id) => id !== disk.by_id),
                      })
                    }
                  />
                  <span className="mono">{shortId(disk)}</span>
                  <span className="zfs_builder_disk_detail">
                    {formatBytes(disk.size_bytes)}
                    {disk.model && ` · ${disk.model}`}
                  </span>
                  {disk.fstype && (
                    <span className="badge badge--warn">
                      {t("ui.zfs.disk_has", { fstype: disk.fstype })}
                    </span>
                  )}
                </label>
              ))}
            </div>

            <div className="zfs_builder_layouts">
              <span className="section_label">{t("ui.zfs.vdev_layout")}</span>
              <div className="zfs_layout_row">
                {LAYOUTS.map((layout) => {
                  const isEnough = builder.devices.length >= layout.minimum;
                  return (
                    <button
                      key={layout.value}
                      type="button"
                      className={`zfs_layout ${builder.layout === layout.value ? "zfs_layout--on" : ""}`}
                      onClick={() =>
                        setBuilder({ ...builder, layout: layout.value })
                      }
                      disabled={!isEnough}
                      title={
                        isEnough
                          ? undefined
                          : t("ui.zfs.layout_needs", { count: layout.minimum })
                      }
                    >
                      <strong>{t(layout.labelKey)}</strong>
                      <span>{t(layout.hintKey)}</span>
                    </button>
                  );
                })}
              </div>
              <p className="field_hint">
                {describeVdev(builder, builderDisks)}
              </p>
            </div>

            {isWipeNeeded && (
              <label className="field zfs_builder_name">
                <span className="field_label">{t("ui.zfs.wipe_label")}</span>
                <input
                  className="input"
                  value={builder.wipeText}
                  placeholder="wipe"
                  onChange={(event) =>
                    setBuilder({ ...builder, wipeText: event.target.value })
                  }
                />
              </label>
            )}

            {errorFor("builder") !== null &&
              (errorFor("builder")?.includes("'-f'") ? (
                <div className="notice notice--warn">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">
                    {friendlyForceReason(errorFor("builder") ?? "")}
                  </div>
                </div>
              ) : (
                <div className="notice notice--error">
                  <Icon name="alert" size={15} />
                  <div className="notice_body">{errorFor("builder")}</div>
                </div>
              ))}

            <div className="zfs_builder_actions">
              {errorFor("builder")?.includes("'-f'") && (
                <button
                  type="button"
                  className="button button--warn"
                  onClick={() => void submitBuilder(true)}
                  disabled={isBusy}
                >
                  {t("ui.zfs.add_anyway")}
                </button>
              )}
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setBuilder(null)}
              >
                {t("ui.zfs.cancel")}
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void submitBuilder()}
                disabled={isBusy || !isBuilderReady}
              >
                {builder.target === "new"
                  ? t("ui.zfs.create_pool")
                  : t("ui.zfs.add_vdev")}
              </button>
            </div>
          </div>
        )}

        {builder === null && (
          <div>
            <button
              type="button"
              className="button"
              onClick={() => openBuilder("new")}
              disabled={isBusy || availableDisks.length === 0}
              title={
                availableDisks.length === 0
                  ? t("ui.zfs.no_spare_build")
                  : undefined
              }
            >
              <Icon name="plus" size={14} />
              {t("ui.zfs.create_pool")}
            </button>
          </div>
        )}
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>{t("ui.zfs.datasets_title")}</h2>
        </div>
        {view.pools.length > 0 && (
          <>
            {view.pools.flatMap((pool) =>
              pool.datasets
                .filter((dataset) => dataset.name !== pool.name)
                .map((dataset) => (
                  <DatasetEditor
                    key={dataset.name}
                    dataset={dataset}
                    isBusy={isBusy}
                    isSambaReady={view.samba.is_ready}
                    onShare={() => setShareTarget(dataset)}
                    onUnshare={() =>
                      void act("datasets", () =>
                        apiPost<ZfsDeviceView>(`${basePath}/datasets/unshare`, {
                          dataset: dataset.name,
                        }),
                      )
                    }
                    onDestroy={() =>
                      confirm.ask({
                        title: t("ui.zfs.dataset_destroy_title", {
                          name: dataset.name,
                        }),
                        body: t("ui.zfs.dataset_destroy_body"),
                        confirmLabel: t("ui.zfs.destroy"),
                        onConfirm: () =>
                          void act("datasets", () =>
                            apiPost<ZfsDeviceView>(
                              `${basePath}/datasets/destroy`,
                              {
                                dataset: dataset.name,
                              },
                            ),
                          ),
                      })
                    }
                  />
                )),
            )}

            {errorFor("datasets") !== null && (
              <div className="notice notice--error">
                <Icon name="alert" size={15} />
                <div className="notice_body">{errorFor("datasets")}</div>
              </div>
            )}

            {isDatasetCreatorOpen ? (
              <div className="zfs_dataset_editor">
                <div className="zfs_dataset_editor_head">
                  <span className="zfs_dataset_editor_title">
                    <Icon name="database" size={13} />
                    {t("ui.zfs.dataset_new")}
                  </span>
                </div>
                <div className="zfs_dataset_fields">
                  <label className="field">
                    <span className="field_label">
                      {t("ui.zfs.dataset_pool")}
                    </span>
                    <select
                      className="select"
                      value={datasetDraft.pool || view.pools[0]?.name || ""}
                      onChange={(event) =>
                        setDatasetDraft({
                          ...datasetDraft,
                          pool: event.target.value,
                        })
                      }
                    >
                      {view.pools.map((pool) => (
                        <option key={pool.name} value={pool.name}>
                          {pool.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span className="field_label">
                      {t("ui.zfs.dataset_name")}
                    </span>
                    <input
                      className="input"
                      value={datasetDraft.name}
                      placeholder="name"
                      onChange={(event) =>
                        setDatasetDraft({
                          ...datasetDraft,
                          name: event.target.value,
                        })
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void submitDatasetCreate();
                        }
                      }}
                    />
                  </label>
                  <label className="field">
                    <span className="field_label">
                      {t("ui.zfs.dataset_mountpoint")}
                    </span>
                    <input
                      className="input"
                      value={datasetDraft.mountpoint}
                      placeholder="/srv/mountpoint"
                      onChange={(event) =>
                        setDatasetDraft({
                          ...datasetDraft,
                          mountpoint: event.target.value,
                        })
                      }
                    />
                    <span className="field_hint">
                      {t("ui.zfs.mountpoint_hint")}
                    </span>
                  </label>
                  <label className="field">
                    <span className="field_label">
                      {t("ui.zfs.compression")}
                    </span>
                    <select
                      className="select"
                      value={datasetDraft.compression}
                      onChange={(event) =>
                        setDatasetDraft({
                          ...datasetDraft,
                          compression: event.target.value,
                        })
                      }
                    >
                      {COMPRESSIONS.map((compression) => (
                        <option key={compression} value={compression}>
                          {compression}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span className="field_label">
                      {t("ui.zfs.record_size")}
                    </span>
                    <select
                      className="select"
                      value={datasetDraft.recordsize}
                      onChange={(event) =>
                        setDatasetDraft({
                          ...datasetDraft,
                          recordsize: event.target.value,
                        })
                      }
                    >
                      {RECORDSIZES.map((recordsize) => (
                        <option key={recordsize} value={recordsize}>
                          {recordsize}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="field_hint">{t("ui.zfs.record_hint")}</p>
                <div className="zfs_builder_actions">
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => setIsDatasetCreatorOpen(false)}
                  >
                    {t("ui.zfs.cancel")}
                  </button>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => void submitDatasetCreate()}
                    disabled={isBusy || datasetDraft.name.trim().length === 0}
                  >
                    {t("ui.zfs.create_dataset")}
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <button
                  type="button"
                  className="button"
                  onClick={() => setIsDatasetCreatorOpen(true)}
                >
                  <Icon name="plus" size={14} />
                  {t("ui.zfs.add_dataset")}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {shareTarget !== null && (
        <ShareModal
          dataset={shareTarget}
          users={view.samba.users}
          isBusy={isBusy}
          error={errorFor("share")}
          onCancel={() => setShareTarget(null)}
          onShare={(users) =>
            void act("share", () =>
              apiPost<ZfsDeviceView>(`${basePath}/datasets/share`, {
                dataset: shareTarget.name,
                users,
              }),
            ).then((isDone) => {
              if (isDone) {
                setShareTarget(null);
              }
            })
          }
        />
      )}
      {confirm.modal}
    </>
  );
}

interface DatasetEditorProps {
  dataset: ZfsDataset;
  isBusy: boolean;
  isSambaReady: boolean;
  onShare: () => void;
  onUnshare: () => void;
  onDestroy: () => void;
}

function DatasetEditor({
  dataset,
  isBusy,
  isSambaReady,
  onShare,
  onUnshare,
  onDestroy,
}: DatasetEditorProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const total = dataset.used_bytes + dataset.available_bytes;
  const usagePercent =
    total > 0 ? Math.round((dataset.used_bytes / total) * 100) : 0;
  const savingsPercent = Math.round((1 - 1 / dataset.compressratio) * 100);

  return (
    <div className="zfs_dataset_editor">
      <div className="zfs_dataset_editor_head">
        <span className="zfs_dataset_editor_title">
          <Icon name="database" size={13} />
          {dataset.name}
        </span>
        <span className="zfs_dataset_mount">{dataset.mountpoint}</span>
        <span className="zfs_member_actions_spacer" />
        {dataset.share !== null ? (
          <>
            <span className="badge badge--accent">
              {t("ui.zfs.share_badge", { share: dataset.share })}
            </span>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={onUnshare}
              disabled={isBusy}
            >
              {t("ui.zfs.unshare")}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button button--small"
            onClick={onShare}
            disabled={isBusy || !isSambaReady}
            title={isSambaReady ? undefined : t("ui.zfs.samba_not_ready")}
          >
            {t("ui.zfs.share")}
          </button>
        )}
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onDestroy}
          disabled={isBusy}
          aria-label={t("ui.zfs.dataset_destroy_title", {
            name: dataset.name,
          })}
        >
          <Icon name="trash" size={13} />
        </button>
      </div>

      <div className="zfs_dataset_stats">
        {dataset.compression === "off"
          ? t("ui.zfs.dataset_stats", {
              compression: dataset.compression,
              recordsize: formatRecordsize(dataset.recordsize_bytes),
              usage: usagePercent,
              used: formatBytes(dataset.used_bytes),
            })
          : t("ui.zfs.dataset_stats_rate", {
              compression: dataset.compression,
              recordsize: formatRecordsize(dataset.recordsize_bytes),
              usage: usagePercent,
              used: formatBytes(dataset.used_bytes),
              rate: Math.max(0, savingsPercent),
            })}
      </div>
    </div>
  );
}

function formatRecordsize(bytes: number): string {
  if (bytes >= 1048576) {
    return `${Math.round(bytes / 1048576)}M`;
  }
  return `${Math.round(bytes / 1024)}K`;
}

interface ShareModalProps {
  dataset: ZfsDataset;
  users: string[];
  isBusy: boolean;
  error: string | null;
  onCancel: () => void;
  onShare: (users: string[]) => void;
}

function ShareModal({
  dataset,
  users,
  isBusy,
  error,
  onCancel,
  onShare,
}: ShareModalProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [selected, setSelected] = useState<string[]>([]);

  const toggleUser = (name: string) => {
    setSelected((current) =>
      current.includes(name)
        ? current.filter((user) => user !== name)
        : [...current, name],
    );
  };

  return createPortal(
    <div className="zfs_modal_backdrop" onClick={onCancel}>
      <div
        className="zfs_modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label={t("ui.zfs.share_title", { name: dataset.name })}
      >
        <h2>{t("ui.zfs.share_title", { name: dataset.name })}</h2>
        <p className="field_hint">
          {t("ui.zfs.share_lead", { mountpoint: dataset.mountpoint })}
        </p>

        <span className="field_label">{t("ui.samba.share_users")}</span>
        {users.length === 0 ? (
          <span className="field_hint">{t("ui.samba.share_users_none")}</span>
        ) : (
          <div className="samba_user_chips">
            <div className="samba_user_chip_list">
              {users.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={`samba_user_chip ${
                    selected.includes(name) ? "samba_user_chip--on" : ""
                  }`}
                  onClick={() => toggleUser(name)}
                >
                  {name}
                </button>
              ))}
            </div>
            <span className="field_hint">
              {selected.length === 0
                ? t("ui.zfs.share_users_all")
                : t("ui.samba.share_users_picked")}
            </span>
          </div>
        )}

        {error !== null && (
          <div className="notice notice--error">
            <Icon name="alert" size={15} />
            <div className="notice_body">{error}</div>
          </div>
        )}

        <div className="zfs_builder_actions">
          <button
            type="button"
            className="button button--ghost"
            onClick={onCancel}
          >
            {t("ui.zfs.cancel")}
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => onShare(selected)}
            disabled={isBusy}
          >
            {t("ui.zfs.share")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** What the selected disk is, physically: rows for the detail list. */
function memberDetailRows(
  member: {
    state: string;
    read_errors: number;
    write_errors: number;
    checksum_errors: number;
  },
  disk: ZfsDisk | null,
): [string, string][] {
  const rows: [string, string][] = [];
  if (disk !== null) {
    rows.push([t("ui.zfs.detail_device"), disk.device]);
    const bus = [disk.transport || null, disk.is_rotational ? "hdd" : "ssd"]
      .filter((part) => part !== null)
      .join(" · ");
    rows.push([t("ui.zfs.detail_bus"), bus]);
    if (disk.by_path !== null) {
      rows.push([t("ui.zfs.detail_path"), disk.by_path]);
    }
    if (disk.model) {
      rows.push([t("ui.zfs.detail_model"), disk.model]);
    }
    if (disk.serial) {
      rows.push([t("ui.zfs.detail_serial"), disk.serial]);
    }
    if (disk.wwn !== null) {
      rows.push([t("ui.zfs.detail_wwn"), disk.wwn]);
    }
    rows.push([t("ui.zfs.detail_size"), formatBytes(disk.size_bytes)]);
    if (disk.smart_passed !== null) {
      const result = disk.smart_passed
        ? t("ui.zfs.smart_passed")
        : t("ui.zfs.smart_failing");
      rows.push([
        t("ui.zfs.detail_smart"),
        disk.temperature_c === null
          ? result
          : t("ui.zfs.smart_with_temp", {
              result,
              temperature: disk.temperature_c,
            }),
      ]);
    }
  }
  rows.push([
    t("ui.zfs.detail_errors"),
    t("ui.zfs.errors_detail", {
      read: member.read_errors,
      write: member.write_errors,
      checksum: member.checksum_errors,
    }),
  ]);
  return rows;
}

/** zpool's refusals in plain words, for the amber confirm they become. */
function friendlyForceReason(message: string): string {
  if (message.includes("mismatched replication")) {
    return t("ui.zfs.force_mismatched");
  }
  if (message.includes("in use") || message.includes("part of")) {
    return t("ui.zfs.force_in_use");
  }
  return t("ui.zfs.force_generic");
}

function shortId(disk: ZfsDisk): string {
  return disk.by_id.split("/").pop() ?? disk.device;
}

function describeVdev(builder: Builder, disks: ZfsDisk[]): string {
  if (disks.length === 0) {
    return t("ui.zfs.vdev_pick_first");
  }
  const smallest = Math.min(...disks.map((disk) => disk.size_bytes));
  const total = disks.reduce((sum, disk) => sum + disk.size_bytes, 0);
  switch (builder.layout) {
    case "single":
      return t("ui.zfs.vdev_single", {
        count: disks.length,
        usable: formatBytes(total),
      });
    case "mirror":
      return t("ui.zfs.vdev_mirror", {
        count: disks.length,
        usable: formatBytes(smallest),
        failures: disks.length - 1,
      });
    case "raidz1":
      return t("ui.zfs.vdev_raidz1", {
        count: disks.length,
        usable: formatBytes(smallest * Math.max(disks.length - 1, 0)),
      });
    case "raidz2":
      return t("ui.zfs.vdev_raidz2", {
        count: disks.length,
        usable: formatBytes(smallest * Math.max(disks.length - 2, 0)),
      });
    default:
      return "";
  }
}
