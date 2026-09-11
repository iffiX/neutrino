import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { NodeCard } from "./node_card";
import { apiDelete, apiPost, apiPut, describeError } from "../api_client";
import { diffNodeDraft, isNodeChanged } from "../node_draft";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";
import { nodeIdFromTag } from "../node_tag";
import { useDraftSeeding } from "../use_draft_seeding";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_NODES } from "../use_hub_events";
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

// What moves this list: a node dying, coming back or moving traffic, which
// the hub's own probe and stats cycle says; and any write to the node file.
const NODES_INVALIDATE_ON = [
  { type: HUB_EVENT_NODES },
  { type: HUB_EVENT_CONFIG },
];

const STRATEGY_LABEL_KEYS: Record<BalancerStrategy, string> = {
  leastPing: "ui.proxy.strategy_least_ping",
  roundRobin: "ui.proxy.strategy_round_robin",
  random: "ui.proxy.strategy_random",
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
  // Redrawn when the panel's language changes.
  useLanguage();
  const resource = useApiResource<NodesResponse>("/proxy/nodes", {
    invalidateOn: NODES_INVALIDATE_ON,
  });
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

  const isReseedable = useDraftSeeding(
    draftBalancer === null ? null : stagedPayload(draftNodes, draftBalancer),
    resource.data === null
      ? null
      : stagedPayload(resource.data.nodes, resource.data.balancer),
  );
  // Whether the list itself was just written. Adding and removing take effect
  // at once, so the answer to one of them owns the draft whatever is staged
  // beside it, or the panel would go on drawing a list the gateway has not
  // got.
  const isListWrittenRef = useRef(false);

  // A tick brings the list, the traffic and what is alive, and it lands in the
  // draft while there is nothing staged in it. A toggle waiting for Apply is
  // the user's: what the gateway says meanwhile does not take it back.
  useEffect(() => {
    if (resource.data === null) {
      return;
    }
    const isListWritten = isListWrittenRef.current;
    isListWrittenRef.current = false;
    const fresh = stagedPayload(resource.data.nodes, resource.data.balancer);
    if (!isListWritten && !isReseedable(fresh)) {
      return;
    }
    setDraftNodes(resource.data.nodes);
    setDraftBalancer(resource.data.balancer);
  }, [resource.data, isReseedable]);

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
      isListWrittenRef.current = true;
      resource.reload();
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemoveNode = (node: NodeView) =>
    confirm.ask({
      title: t("ui.proxy.node_remove_title", { name: node.name }),
      body: t("ui.proxy.node_remove_body"),
      confirmLabel: t("ui.proxy.node_remove_confirm"),
      onConfirm: () => void removeNode(node),
    });

  const removeNode = async (node: NodeView) => {
    setActionError(null);
    try {
      await apiDelete<NodesResponse>(`/proxy/nodes/${node.id}`);
      isListWrittenRef.current = true;
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
  // What the frame and the bar both read. Adding or removing a node writes it
  // at once, so there is no draft to be dirty about and the panel would sit
  // unlit beside a lit Apply — the glow and the button have to answer the same
  // question, which is "is there something here to apply".
  const isUnapplied = (diff?.isDirty ?? false) || isSavedNotApplied;

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
      className={`settings_group ${isUnapplied ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t("ui.proxy.nodes_title")}</h2>
      </div>
      <p className="field_hint">{t("ui.proxy.nodes_hint")}</p>

      {actionError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{actionError}</div>
        </div>
      )}

      <div className="nodes_toolbar">
        <div className="nodes_toolbar_group">
          <label className="field nodes_toolbar_field">
            <span className="field_label">{t("ui.proxy.strategy_label")}</span>
            <select
              className="select"
              value={draftBalancer?.strategy ?? "leastPing"}
              disabled={draftBalancer === null}
              onChange={(event) =>
                handleStrategyChange(event.target.value as BalancerStrategy)
              }
            >
              {Object.entries(STRATEGY_LABEL_KEYS).map(([strategy, key]) => (
                <option key={strategy} value={strategy}>
                  {t(key)}
                </option>
              ))}
            </select>
          </label>

          <label className="field nodes_toolbar_field">
            <span className="field_label">
              {t("ui.proxy.probe_interval_label")}
            </span>
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

        <div className="nodes_toolbar_actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIsAddOpen((open) => !open)}
          >
            <Icon name="plus" size={14} />
            {t("ui.proxy.node_add")}
          </button>
          <button
            type="button"
            className="button"
            onClick={() => void handleTestAll()}
            disabled={testingIds.length > 0 || draftNodes.length === 0}
          >
            <Icon name="bolt" size={14} />
            {testingIds.length > 0
              ? t("ui.proxy.node_testing_all")
              : t("ui.proxy.node_test_all")}
          </button>
        </div>
      </div>

      {isAddOpen && (
        <form
          className="nodes_add"
          onSubmit={(event) => void handleAddNode(event)}
        >
          <label className="field">
            <span className="field_label">
              {t("ui.proxy.share_link_label")}
            </span>
            <input
              className="input"
              value={shareLink}
              placeholder="ss://… or vless://…"
              autoFocus
              onChange={(event) => setShareLink(event.target.value)}
            />
            <span className="field_hint">{t("ui.proxy.share_link_hint")}</span>
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
              {t("ui.proxy.node_add_cancel")}
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={isAdding || shareLink.trim().length === 0}
            >
              <Icon name="plus" size={14} />
              {isAdding
                ? t("ui.proxy.node_adding")
                : t("ui.proxy.node_add_submit")}
            </button>
          </div>
        </form>
      )}

      <div className="nodes_summary">
        <span>{t("ui.proxy.summary_enabled", { count: enabledCount })}</span>
        <span>{t("ui.proxy.summary_alive", { count: aliveCount })}</span>
        <span>{t("ui.proxy.summary_total", { count: draftNodes.length })}</span>
        <span>
          {t("ui.proxy.summary_moved", { bytes: formatBytes(totalTraffic) })}
        </span>
        <span>
          {t("ui.proxy.summary_probe", {
            url: draftBalancer?.probe_url ?? "—",
          })}
        </span>
      </div>

      {resource.isLoading && draftNodes.length === 0 ? (
        <div className="nodes_grid">
          <div className="skeleton" style={{ height: 230 }} />
          <div className="skeleton" style={{ height: 230 }} />
          <div className="skeleton" style={{ height: 230 }} />
        </div>
      ) : draftNodes.length === 0 ? (
        <div className="placeholder">
          <span>{t("ui.proxy.nodes_empty")}</span>
          <span className="faint">{t("ui.proxy.nodes_empty_hint")}</span>
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
        isDirty={isUnapplied}
        isBusy={isApplying}
        label={t("ui.proxy.apply_nodes")}
        hint={
          isSavedNotApplied
            ? t("ui.proxy.apply_nodes_hint")
            : (diff?.summary ?? "")
        }
        warning={t("ui.proxy.warning_restart")}
        notice={applyMessage}
        onReset={handleDiscard}
        onApply={() => void handleApply()}
      />
      {confirm.modal}
    </div>
  );
}

/**
 * What this panel stages, and nothing else.
 *
 * Which nodes are on, what they are called and how the balancer picks. What a
 * node is doing — alive, its latency, what it has moved — is the gateway's
 * answer and lands in the draft on its own, so counting it here would read a
 * probe coming back as somebody's edit.
 */
function stagedPayload(nodes: NodeView[], balancer: BalancerSettings): string {
  return JSON.stringify([
    nodes.map((node) => [node.id, node.name, node.is_enabled]),
    balancer,
  ]);
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
