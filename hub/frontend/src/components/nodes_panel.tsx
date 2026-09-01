import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { NodeCard } from "./node_card";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { diffNodeDraft, isNodeChanged } from "../node_draft";
import { formatBytes } from "../format_bytes";
import { nodeIdFromTag } from "../node_tag";
import { useApiResource } from "../use_api_resource";
import { useConfirm } from "../use_confirm";
import { useLiveStats } from "../use_live_stats";
import type {
  BalancerSettings,
  BalancerStrategy,
  ApplyResult,
  NodeTestResult,
  NodeView,
  NodesResponse,
} from "../api_types";

import "./nodes_panel.css";

/**
 * The exit nodes and how traffic is balanced between them.
 *
 * Enabling and renaming are drafts until the apply bar is used. That is not
 * ceremony: applying rewrites the xray config and restarts the proxy, which
 * drops every live connection on the LAN, so the panel states exactly what
 * will change and makes the user ask for it.
 *
 * Adding and removing are the exceptions, and take effect on the list at once.
 * A node that does not exist yet has no draft state to describe, and one that
 * has been deleted has none left; carrying either through the diff would mean
 * inventing a way to say it.
 */

const PROBE_HISTORY_LENGTH = 12;

const STRATEGY_LABELS: Record<BalancerStrategy, string> = {
  leastPing: "leastPing — lowest latency wins",
  roundRobin: "roundRobin — cycle through nodes",
  random: "random — pick per connection",
};

interface NodesPanelProps {
  /**
   * Called when the list changes, because the list decides something outside
   * it: a proxy with no enabled node is switched off, and the page holding
   * that switch has to read it again rather than go on drawing the answer it
   * fetched on mount.
   */
  onNodesChanged: () => void;
}

export function NodesPanel({ onNodesChanged }: NodesPanelProps) {
  const resource = useApiResource<NodesResponse>("/proxy/nodes");
  const { latestFrame } = useLiveStats();

  const [draftNodes, setDraftNodes] = useState<NodeView[]>([]);
  const [draftBalancer, setDraftBalancer] = useState<BalancerSettings | null>(
    null,
  );
  const [probeHistory, setProbeHistory] = useState<Record<string, number[]>>(
    {},
  );
  const [testingIds, setTestingIds] = useState<string[]>([]);
  const [isApplying, setIsApplying] = useState(false);
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [shareLink, setShareLink] = useState("");
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const confirm = useConfirm();

  useEffect(() => {
    if (resource.data === null) {
      return;
    }
    setDraftNodes(resource.data.nodes);
    setDraftBalancer(resource.data.balancer);
  }, [resource.data]);

  useEffect(() => {
    if (latestFrame === null) {
      return;
    }
    setProbeHistory((previous) => {
      const next: Record<string, number[]> = { ...previous };
      for (const probe of latestFrame.nodes) {
        // Probes arrive tagged `node_<id>`; the cards look themselves up by
        // bare id, so the series has to be keyed the way it is read.
        const nodeId = nodeIdFromTag(probe.tag);
        if (nodeId === null || probe.delay_ms === null) {
          continue;
        }
        const series = next[nodeId] ?? [];
        next[nodeId] = [...series, probe.delay_ms].slice(-PROBE_HISTORY_LENGTH);
      }
      return next;
    });
  }, [latestFrame]);

  const applied = resource.data;
  const diff =
    applied === null || draftBalancer === null
      ? null
      : diffNodeDraft(
          applied.nodes,
          draftNodes,
          applied.balancer,
          draftBalancer,
        );

  const handleToggleNode = (nodeId: string, isEnabled: boolean) => {
    setApplyMessage(null);
    setDraftNodes((nodes) =>
      nodes.map((node) =>
        node.id === nodeId ? { ...node, is_enabled: isEnabled } : node,
      ),
    );
  };

  const handleStrategyChange = (strategy: BalancerStrategy) => {
    setApplyMessage(null);
    setDraftBalancer((balancer) =>
      balancer === null ? balancer : { ...balancer, strategy },
    );
  };

  const handleProbeIntervalChange = (value: string) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return;
    }
    setDraftBalancer((balancer) =>
      balancer === null ? balancer : { ...balancer, probe_interval_s: parsed },
    );
  };

  const handleTestNode = async (nodeId: string) => {
    setActionError(null);
    setTestingIds((ids) => [...ids, nodeId]);
    try {
      const result = await apiPost<NodeTestResult>(
        `/proxy/nodes/${nodeId}/test`,
      );
      applyTestResult(nodeId, result, setDraftNodes, setProbeHistory);
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setTestingIds((ids) => ids.filter((id) => id !== nodeId));
    }
  };

  const handleTestAll = async () => {
    setActionError(null);
    const ids = draftNodes.map((node) => node.id);
    setTestingIds(ids);
    try {
      const results = await Promise.all(
        ids.map(async (nodeId) => ({
          nodeId,
          result: await apiPost<NodeTestResult>(`/proxy/nodes/${nodeId}/test`),
        })),
      );
      for (const { nodeId, result } of results) {
        applyTestResult(nodeId, result, setDraftNodes, setProbeHistory);
      }
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setTestingIds([]);
    }
  };

  const handleAddNode = async (event: FormEvent) => {
    event.preventDefault();
    const link = shareLink.trim();
    if (link.length === 0) {
      return;
    }
    setIsAdding(true);
    setActionError(null);
    try {
      await apiPost<NodeView>("/proxy/nodes", { link });
      setShareLink("");
      setIsAddOpen(false);
      resource.reload();
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemoveNode = (node: NodeView) =>
    confirm.ask({
      title: `Remove ${node.name}`,
      body: "The exit node is deleted and its share link is not kept.",
      confirmLabel: "Remove",
      onConfirm: () => void removeNode(node),
    });

  const removeNode = async (node: NodeView) => {
    setActionError(null);
    try {
      await apiDelete<NodesResponse>(`/proxy/nodes/${node.id}`);
      resource.reload();
      onNodesChanged();
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    }
  };

  const handleDiscard = () => {
    if (applied === null) {
      return;
    }
    setDraftNodes(applied.nodes);
    setDraftBalancer(applied.balancer);
    setApplyMessage(null);
  };

  const handleApply = async () => {
    if (applied === null || draftBalancer === null || diff === null) {
      return;
    }
    setIsApplying(true);
    setActionError(null);
    setApplyMessage(null);
    try {
      for (const node of draftNodes) {
        if (isNodeChanged(applied.nodes, node)) {
          await apiPut<NodeView>(`/proxy/nodes/${node.id}`, {
            is_enabled: node.is_enabled,
            name: node.name,
          });
        }
      }
      if (diff.isBalancerChanged) {
        await apiPut<BalancerSettings>("/proxy/balancer", draftBalancer);
      }
      const result = await apiPost<ApplyResult>("/proxy/apply");
      setApplyMessage(result.message);
      resource.reload();
      onNodesChanged();
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setIsApplying(false);
    }
  };

  if (resource.error !== null && resource.data === null) {
    return <ErrorPanel message={resource.error} onRetry={resource.reload} />;
  }

  // Adding or removing a node writes it at once — there is no draft of a list
  // membership to hold — so the gateway can be carrying a configuration this
  // panel has nothing dirty about. Applying is still what makes it run, which
  // is why the bar has to be pressable in exactly that state.
  const isSavedNotApplied =
    (applied?.is_dirty ?? false) && !(diff?.isDirty ?? false);

  const enabledCount = draftNodes.filter((node) => node.is_enabled).length;
  const aliveCount = draftNodes.filter((node) => node.is_alive).length;
  const totalTraffic = draftNodes.reduce(
    (total, node) => total + node.uplink_bytes + node.downlink_bytes,
    0,
  );

  return (
    // The panel owns the draft, so it draws its own frame: a parent cannot
    // know this box has unsaved changes, and the glow that says so has to come
    // from whatever holds the state.
    <div
      className={`settings_group ${
        diff?.isDirty ? "settings_group--dirty" : ""
      }`}
    >
      <div className="settings_group_title">
        <h2>Exit nodes</h2>
      </div>
      <p className="field_hint">
        Where proxied traffic leaves the internet. The balancer picks between
        the enabled ones by the strategy below.
      </p>

      {actionError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{actionError}</div>
        </div>
      )}

      <div className="nodes_toolbar">
        <div className="nodes_toolbar_group">
          <label className="field nodes_toolbar_field">
            <span className="field_label">Balancer strategy</span>
            <select
              className="select"
              value={draftBalancer?.strategy ?? "leastPing"}
              disabled={draftBalancer === null}
              onChange={(event) =>
                handleStrategyChange(event.target.value as BalancerStrategy)
              }
            >
              {Object.entries(STRATEGY_LABELS).map(([strategy, label]) => (
                <option key={strategy} value={strategy}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className="field nodes_toolbar_field">
            <span className="field_label">Probe interval (s)</span>
            <input
              className="input"
              inputMode="numeric"
              value={draftBalancer?.probe_interval_s ?? ""}
              disabled={draftBalancer === null}
              onChange={(event) =>
                handleProbeIntervalChange(event.target.value)
              }
            />
          </label>
        </div>

        <div className="page_actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIsAddOpen((open) => !open)}
          >
            <Icon name="plus" size={14} />
            Add node
          </button>
          <button
            type="button"
            className="button"
            onClick={() => void handleTestAll()}
            disabled={testingIds.length > 0 || draftNodes.length === 0}
          >
            <Icon name="bolt" size={14} />
            {testingIds.length > 0 ? "Testing…" : "Test all"}
          </button>
          <button type="button" className="button" onClick={resource.reload}>
            <Icon name="refresh" size={14} />
            Reload
          </button>
        </div>
      </div>

      {isAddOpen && (
        <form
          className="nodes_add"
          onSubmit={(event) => void handleAddNode(event)}
        >
          <label className="field">
            <span className="field_label">Share link</span>
            <input
              className="input"
              value={shareLink}
              placeholder="ss://… or vless://…"
              autoFocus
              onChange={(event) => setShareLink(event.target.value)}
            />
            <span className="field_hint">
              Paste the link as the provider gives it.
            </span>
          </label>
          <div className="button_row">
            <button
              type="button"
              className="button button--ghost"
              onClick={() => {
                setIsAddOpen(false);
                setShareLink("");
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={isAdding || shareLink.trim().length === 0}
            >
              <Icon name="plus" size={14} />
              {isAdding ? "Adding…" : "Add"}
            </button>
          </div>
        </form>
      )}

      <div className="nodes_summary">
        <span>{enabledCount} enabled</span>
        <span>{aliveCount} alive</span>
        <span>{draftNodes.length} total</span>
        <span>{formatBytes(totalTraffic)} moved</span>
        <span>probe: {draftBalancer?.probe_url ?? "—"}</span>
      </div>

      {resource.isLoading && draftNodes.length === 0 ? (
        <div className="nodes_grid">
          <div className="skeleton" style={{ height: 230 }} />
          <div className="skeleton" style={{ height: 230 }} />
          <div className="skeleton" style={{ height: 230 }} />
        </div>
      ) : draftNodes.length === 0 ? (
        <div className="placeholder">
          <span>No nodes configured</span>
          <span className="faint">
            Add one with a share link from your provider.
          </span>
        </div>
      ) : (
        <div className="nodes_grid">
          {draftNodes.map((node) => (
            <NodeCard
              key={node.id}
              node={node}
              probeHistory={probeHistory[node.id] ?? []}
              isDirty={applied !== null && isNodeChanged(applied.nodes, node)}
              isTesting={testingIds.includes(node.id)}
              onToggle={(isEnabled) => handleToggleNode(node.id, isEnabled)}
              onTest={() => void handleTestNode(node.id)}
              onRemove={() => handleRemoveNode(node)}
            />
          ))}
        </div>
      )}

      <ApplyBar
        isDirty={(diff?.isDirty ?? false) || isSavedNotApplied}
        isBusy={isApplying}
        label="Apply nodes"
        hint={
          isSavedNotApplied
            ? "Loads the exit nodes into the running proxy."
            : (diff?.summary ?? "")
        }
        warning="Restarts the proxy; connections through it drop."
        notice={applyMessage}
        onReset={handleDiscard}
        onApply={() => void handleApply()}
      />
      {confirm.modal}
    </div>
  );
}

function applyTestResult(
  nodeId: string,
  result: NodeTestResult,
  setDraftNodes: (updater: (nodes: NodeView[]) => NodeView[]) => void,
  setProbeHistory: (
    updater: (history: Record<string, number[]>) => Record<string, number[]>,
  ) => void,
) {
  setDraftNodes((nodes) =>
    nodes.map((node) =>
      node.id === nodeId
        ? { ...node, is_alive: result.is_alive, delay_ms: result.delay_ms }
        : node,
    ),
  );
  if (result.delay_ms === null) {
    return;
  }
  const delayMs = result.delay_ms;
  setProbeHistory((history) => ({
    ...history,
    [nodeId]: [...(history[nodeId] ?? []), delayMs].slice(
      -PROBE_HISTORY_LENGTH,
    ),
  }));
}
