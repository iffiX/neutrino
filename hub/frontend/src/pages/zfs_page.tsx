import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { ErrorPanel } from "../components/error_panel";
import { Icon } from "../components/icon";
import { ZfsTopology } from "../components/zfs_topology";
import { apiDelete, apiGet, apiPost, describeError } from "../api_client";
import { formatBytes } from "../format_bytes";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import type { ZfsDataset, ZfsDisk, ZfsView } from "../api_types";

import "./samba_page.css";
import "./zfs_page.css";

/**
 * Storage: the topology, the pools, the datasets.
 *
 * There is no draft-and-apply here — a pool's truth is on its disks, so the
 * page is a live viewport with guarded verbs. The dangerous ones ask
 * properly: wiping disks and destroying pools want words typed back, exactly
 * as uninstalling a module does.
 */

const POLL_INTERVAL_MS = 5000;
const SCAN_POLL_INTERVAL_MS = 2500;

const LAYOUTS: {
  value: string;
  label: string;
  minimum: number;
  hint: string;
}[] = [
  { value: "single", label: "Single", minimum: 1, hint: "No redundancy" },
  { value: "mirror", label: "Mirror", minimum: 2, hint: "Full copies" },
  { value: "raidz1", label: "RAID-Z1", minimum: 3, hint: "Survives 1 disk" },
  { value: "raidz2", label: "RAID-Z2", minimum: 4, hint: "Survives 2 disks" },
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

export function ZfsPage() {
  const zfs = useApiResource<ZfsView>("/zfs");

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
  const isScanning =
    view?.pools.some((pool) => pool.scan.kind !== null) ?? false;

  // Resilvers and scrubs move on their own; the page keeps up quietly.
  useEffect(() => {
    let isCancelled = false;
    const poll = async () => {
      try {
        const fresh = await apiGet<ZfsView>("/zfs");
        if (!isCancelled) {
          zfs.setData(fresh);
        }
      } catch {
        // A transient failure is ignored; the next tick tries again.
      }
    };
    const handle = window.setInterval(
      () => void poll(),
      isScanning ? SCAN_POLL_INTERVAL_MS : POLL_INTERVAL_MS,
    );
    return () => {
      isCancelled = true;
      window.clearInterval(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isScanning]);

  const act = async (scope: string, work: () => Promise<ZfsView>) => {
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
    return (
      <div className="page">
        <h1>ZFS</h1>
        <ErrorPanel message={zfs.error} onRetry={zfs.reload} />
      </div>
    );
  }
  if (view === null) {
    return (
      <div className="page">
        <h1>ZFS</h1>
        <div className="skeleton" style={{ height: 240 }} />
      </div>
    );
  }
  if (!view.is_installed) {
    return (
      <div className="page">
        <h1>ZFS</h1>
        <div className="placeholder">
          <span>The ZFS tools are not installed</span>
          <span className="faint">Install the zfs module from Services.</span>
        </div>
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
        ? apiPost<ZfsView>("/zfs/pools", { ...body, name: builder.name.trim() })
        : apiPost<ZfsView>(`/zfs/pools/${builder.target}/expand`, body),
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
      apiPost<ZfsView>(`/zfs/pools/${selectedMember.pool}/replace`, {
        old_device: selectedMember.device,
        new_device: replaceWith,
      }),
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
      apiPost<ZfsView>("/zfs/datasets", {
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
    <div className="page">
      <div className="page_header">
        <div className="page_header_text">
          <h1>ZFS</h1>
        </div>
      </div>

      {view.importable.map((candidate) => (
        <div className="notice" key={candidate.name}>
          <Icon name="database" size={15} />
          <div className="notice_body">
            Pool <span className="mono">{candidate.name}</span> (
            {candidate.state.toLowerCase()}) found on attached disks.
          </div>
          <button
            type="button"
            className="button button--small"
            onClick={() =>
              void act("import", () =>
                apiPost<ZfsView>(`/zfs/import/${candidate.name}`),
              )
            }
            disabled={isBusy}
          >
            Import
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
          <h2>Topology</h2>
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
                        ? "No spare disk to replace with"
                        : undefined
                    }
                  >
                    Replace
                  </button>
                  {member.state === "OFFLINE" ? (
                    <button
                      type="button"
                      className="button button--small"
                      onClick={() =>
                        void act("member", () =>
                          apiPost<ZfsView>(
                            `/zfs/pools/${selectedMember.pool}/online`,
                            { device: selectedMember.device },
                          ),
                        )
                      }
                      disabled={isBusy}
                    >
                      Online
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button button--small"
                      onClick={() =>
                        void act("member", () =>
                          apiPost<ZfsView>(
                            `/zfs/pools/${selectedMember.pool}/offline`,
                            { device: selectedMember.device },
                          ),
                        )
                      }
                      disabled={isBusy}
                    >
                      Offline
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
                    <option value="">replacement disk…</option>
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
                    Start resilver
                  </button>
                  <button
                    type="button"
                    className="button button--ghost button--small"
                    onClick={() => {
                      setIsReplacing(false);
                      setReplaceWith(null);
                    }}
                  >
                    Cancel
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
          <h2>Pools</h2>
        </div>
        {view.pools.length === 0 ? (
          <div className="placeholder">
            <span>No pools yet</span>
            <span className="faint">
              Pick spare disks and create one, or plug in disks that already
              hold a pool.
            </span>
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
                    {pool.capacity_percent}% full
                  </span>
                )}
                <span className="zfs_pool_numbers">
                  {formatBytes(pool.allocated_bytes)} /{" "}
                  {formatBytes(pool.size_bytes)} · {pool.fragmentation_percent}%
                  frag
                </span>
                <span className="zfs_member_actions_spacer" />
                {pool.scan.kind !== null ? (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() =>
                      void act(`pool:${pool.name}`, () =>
                        apiPost<ZfsView>(`/zfs/pools/${pool.name}/scrub/stop`),
                      )
                    }
                    disabled={isBusy}
                  >
                    Stop {pool.scan.kind}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() =>
                      void act(`pool:${pool.name}`, () =>
                        apiPost<ZfsView>(`/zfs/pools/${pool.name}/scrub`),
                      )
                    }
                    disabled={isBusy}
                  >
                    Scrub
                  </button>
                )}
                <button
                  type="button"
                  className="button button--small"
                  onClick={() => openBuilder(pool.name)}
                  disabled={isBusy || availableDisks.length === 0}
                  title={
                    availableDisks.length === 0
                      ? "No spare disks to grow with"
                      : undefined
                  }
                >
                  Expand
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
                    {pool.scan.kind} {pool.scan.percent?.toFixed(1) ?? "?"}%
                    {pool.scan.eta !== null && ` · ${pool.scan.eta} to go`}
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
                    Destroying <span className="mono">{pool.name}</span> erases
                    every dataset on it. Type the pool name to continue.
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
                        apiDelete<ZfsView>(`/zfs/pools/${pool.name}`),
                      ).then((isDone) => {
                        if (isDone) {
                          setDestroyConfirm(null);
                        }
                      })
                    }
                  >
                    Destroy pool
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
                  ? "Create pool"
                  : `Expand ${builder.target}`}
              </h3>
            </div>
            {builder.target !== "new" && (
              <p className="field_hint">
                The new vdev joins the pool permanently; it cannot be removed
                later.
              </p>
            )}

            {builder.target === "new" && (
              <label className="field zfs_builder_name">
                <span className="field_label">Pool name</span>
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
                  ? "First vdev disks"
                  : "New vdev disks"}
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
                    <span className="badge badge--warn">has {disk.fstype}</span>
                  )}
                </label>
              ))}
            </div>

            <div className="zfs_builder_layouts">
              <span className="section_label">Vdev layout</span>
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
                          : `needs at least ${layout.minimum} disks`
                      }
                    >
                      <strong>{layout.label}</strong>
                      <span>{layout.hint}</span>
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
                <span className="field_label">
                  Selected disks carry data; type wipe to erase them
                </span>
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
                  Add anyway
                </button>
              )}
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setBuilder(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void submitBuilder()}
                disabled={isBusy || !isBuilderReady}
              >
                {builder.target === "new" ? "Create pool" : "Add vdev"}
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
                  ? "No spare disks to build from"
                  : undefined
              }
            >
              <Icon name="plus" size={14} />
              Create pool
            </button>
          </div>
        )}
      </section>

      <section className="settings_group">
        <div className="settings_group_title">
          <h2>Datasets</h2>
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
                        apiPost<ZfsView>("/zfs/datasets/unshare", {
                          dataset: dataset.name,
                        }),
                      )
                    }
                    onDestroy={() =>
                      confirm.ask({
                        title: `Destroy ${dataset.name}`,
                        body:
                          "The dataset and every file on it are removed from " +
                          "the pool. There is no snapshot to return to unless " +
                          "one was taken.",
                        confirmLabel: "Destroy",
                        onConfirm: () =>
                          void act("datasets", () =>
                            apiPost<ZfsView>("/zfs/datasets/destroy", {
                              dataset: dataset.name,
                            }),
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
                    new dataset
                  </span>
                </div>
                <div className="zfs_dataset_fields">
                  <label className="field">
                    <span className="field_label">Pool</span>
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
                    <span className="field_label">Name</span>
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
                    <span className="field_label">Mountpoint</span>
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
                      Blank keeps the default /pool/name.
                    </span>
                  </label>
                  <label className="field">
                    <span className="field_label">Compression</span>
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
                    <span className="field_label">Record size</span>
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
                <p className="field_hint">
                  Small records suit databases and VM images; large ones suit
                  media and archives.
                </p>
                <div className="zfs_builder_actions">
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => setIsDatasetCreatorOpen(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => void submitDatasetCreate()}
                    disabled={isBusy || datasetDraft.name.trim().length === 0}
                  >
                    Create dataset
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
                  Add dataset
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
              apiPost<ZfsView>("/zfs/datasets/share", {
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
    </div>
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
            <span className="badge badge--accent">smb · {dataset.share}</span>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={onUnshare}
              disabled={isBusy}
            >
              Unshare
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button button--small"
            onClick={onShare}
            disabled={isBusy || !isSambaReady}
            title={isSambaReady ? undefined : "Install and start Samba first"}
          >
            Share
          </button>
        )}
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={onDestroy}
          disabled={isBusy}
          aria-label={`Destroy ${dataset.name}`}
        >
          <Icon name="trash" size={13} />
        </button>
      </div>

      <div className="zfs_dataset_stats">
        compression {dataset.compression} · recordsize{" "}
        {formatRecordsize(dataset.recordsize_bytes)} · usage {usagePercent}% ·{" "}
        {formatBytes(dataset.used_bytes)} used
        {dataset.compression !== "off" &&
          ` · compression rate ${Math.max(0, savingsPercent)}%`}
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
        aria-label={`Share ${dataset.name}`}
      >
        <h2>
          Share <span className="mono">{dataset.name}</span>
        </h2>
        <p className="field_hint">
          Exports {dataset.mountpoint} over SMB, read-write for the chosen
          users.
        </p>

        <span className="field_label">Who may use it</span>
        {users.length === 0 ? (
          <span className="field_hint">
            Every user — none are configured yet.
          </span>
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
                ? "None picked: every user may use it, future ones included."
                : "Only the picked users may use it."}
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
            Cancel
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => onShare(selected)}
            disabled={isBusy}
          >
            Share
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
    rows.push(["Device", disk.device]);
    const bus = [disk.transport || null, disk.is_rotational ? "hdd" : "ssd"]
      .filter((part) => part !== null)
      .join(" · ");
    rows.push(["Bus", bus]);
    if (disk.by_path !== null) {
      rows.push(["Path", disk.by_path]);
    }
    if (disk.model) {
      rows.push(["Model", disk.model]);
    }
    if (disk.serial) {
      rows.push(["Serial", disk.serial]);
    }
    if (disk.wwn !== null) {
      rows.push(["WWN", disk.wwn]);
    }
    rows.push(["Size", formatBytes(disk.size_bytes)]);
    if (disk.smart_passed !== null) {
      rows.push([
        "SMART",
        `${disk.smart_passed ? "passed" : "FAILING"}${
          disk.temperature_c !== null ? ` · ${disk.temperature_c}°C` : ""
        }`,
      ]);
    }
  }
  rows.push([
    "Errors",
    `${member.read_errors} read · ${member.write_errors} write · ${member.checksum_errors} cksum`,
  ]);
  return rows;
}

/** zpool's refusals in plain words, for the amber confirm they become. */
function friendlyForceReason(message: string): string {
  if (message.includes("mismatched replication")) {
    return "This layout does not match the pool's existing vdevs — the pool would only be as safe as its weakest vdev. Add anyway?";
  }
  if (message.includes("in use") || message.includes("part of")) {
    return "A chosen disk still carries traces of an earlier pool or filesystem; adding will overwrite them. Add anyway?";
  }
  return "zpool wants explicit confirmation for this combination. Add anyway?";
}

function shortId(disk: ZfsDisk): string {
  return disk.by_id.split("/").pop() ?? disk.device;
}

function describeVdev(builder: Builder, disks: ZfsDisk[]): string {
  if (disks.length === 0) {
    return "Pick the disks first; the layouts unlock by count.";
  }
  const smallest = Math.min(...disks.map((disk) => disk.size_bytes));
  const total = disks.reduce((sum, disk) => sum + disk.size_bytes, 0);
  switch (builder.layout) {
    case "single":
      return `${disks.length} disk striped: ${formatBytes(total)} usable, no disk may fail.`;
    case "mirror":
      return `${disks.length}-way mirror: ${formatBytes(smallest)} usable, survives ${disks.length - 1} failed disk(s).`;
    case "raidz1":
      return `raidz1 over ${disks.length}: ~${formatBytes(smallest * Math.max(disks.length - 1, 0))} usable, survives 1 failed disk.`;
    case "raidz2":
      return `raidz2 over ${disks.length}: ~${formatBytes(smallest * Math.max(disks.length - 2, 0))} usable, survives 2 failed disks.`;
    default:
      return "";
  }
}
