import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ApplyBar } from "./apply_bar";
import { ErrorPanel } from "./error_panel";
import { Icon } from "./icon";
import { NodeCard } from "./node_card";
import { apiPost, describeError } from "../api_client";
import { diffNodeDraft, isNodeChanged } from "../node_draft";
import { formatBytes } from "../format_bytes";
import { t, useLanguage } from "../i18n";
import { useDraftSeeding } from "../use_draft_seeding";
import { useApiResource } from "../use_api_resource";
import { HUB_EVENT_CONFIG, HUB_EVENT_NODES } from "../use_hub_events";
import { useConfirm } from "../use_confirm";
import type {
  BalancerSettings,
  ApplyResult,
  NodeTestRequest,
  NodeView,
  NodesResponse,
} from "../api_types";

import "./nodes_panel.css";

/**
 * The exit nodes, and how the hub measures them.
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
 *
 * Testing is neither. It writes nothing and stages nothing: it asks the hub
 * to measure now and replaces the list with the readings that come back.
 */

// What moves this list: a node dying, coming back or moving traffic, which
// the hub's own probe and stats cycle says; and any write to the node file.
const NODES_INVALIDATE_ON = [
  { type: HUB_EVENT_NODES },
  { type: HUB_EVENT_CONFIG },
];

/** Every word this panel says. */
const TEXT_KEYS = {
  title: "ui.proxy.nodes_title",
  hint: "ui.proxy.nodes_hint",
  probeUrlLabel: "ui.proxy.probe_url_label",
  probeUrlHint: "ui.proxy.probe_url_hint",
  referenceUrlLabel: "ui.proxy.reference_url_label",
  referenceUrlHint: "ui.proxy.reference_url_hint",
  probeIntervalLabel: "ui.proxy.probe_interval_label",
  probeIntervalHint: "ui.proxy.probe_interval_hint",
  nodeAdd: "ui.proxy.node_add",
  nodeAddCancel: "ui.proxy.node_add_cancel",
  nodeAddSubmit: "ui.proxy.node_add_submit",
  nodeAdding: "ui.proxy.node_adding",
  shareLinkLabel: "ui.proxy.share_link_label",
  shareLinkHint: "ui.proxy.share_link_hint",
  testAll: "ui.proxy.node_test_all",
  testingAll: "ui.proxy.node_testing_all",
  removeTitle: "ui.proxy.node_remove_title",
  removeBody: "ui.proxy.node_remove_body",
  removeConfirm: "ui.proxy.node_remove_confirm",
  summaryEnabled: "ui.proxy.summary_enabled",
  summaryAlive: "ui.proxy.summary_alive",
  summaryTotal: "ui.proxy.summary_total",
  summaryMoved: "ui.proxy.summary_moved",
  empty: "ui.proxy.nodes_empty",
  emptyHint: "ui.proxy.nodes_empty_hint",
  applyLabel: "ui.proxy.apply_nodes",
  applyHint: "ui.proxy.apply_nodes_hint",
  applyWarning: "ui.proxy.warning_restart",
};

const SKELETON_HEIGHT = 230;

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
  const resource = useApiResource<NodesResponse>("/hub/proxy/node", {
    invalidateOn: NODES_INVALIDATE_ON,
  });

  const [draftNodes, setDraftNodes] = useState<NodeView[]>([]);
  const [draftBalancer, setDraftBalancer] = useState<BalancerSettings | null>(
    null,
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

  // A tick brings the list, the traffic and the measurements, and it lands in
  // the draft while there is nothing staged in it. A toggle waiting for Apply
  // is the user's: what the gateway says meanwhile does not take it back.
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

  const handleProbeUrlChange = (probeUrl: string) => {
    setApplyMessage(null);
    setDraftBalancer((balancer) =>
      balancer === null ? balancer : { ...balancer, probe_url: probeUrl },
    );
  };

  const handleReferenceUrlChange = (referenceUrl: string) => {
    setApplyMessage(null);
    setDraftBalancer((balancer) =>
      balancer === null
        ? balancer
        : { ...balancer, reference_url: referenceUrl },
    );
  };

  const handleProbeIntervalChange = (value: string) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return;
    }
    setApplyMessage(null);
    setDraftBalancer((balancer) =>
      balancer === null ? balancer : { ...balancer, probe_interval_s: parsed },
    );
  };

  // A measurement is not an edit, so it goes nowhere near the draft: the hub
  // measures, answers with the whole list, and that answer replaces what is
  // applied. The draft picks it up the way any other tick lands in it.
  const handleTestNode = async (nodeId: string) => {
    setActionError(null);
    setTestingIds((ids) => [...ids, nodeId]);
    const request: NodeTestRequest = { node_id: nodeId };
    try {
      resource.setData(
        await apiPost<NodesResponse>("/hub/proxy/node/test", request),
      );
    } catch (cause: unknown) {
      setActionError(describeError(cause));
    } finally {
      setTestingIds((ids) => ids.filter((id) => id !== nodeId));
    }
  };

  // A request naming no node means every node, in one request rather than one
  // per card.
  const handleTestAll = async () => {
    setActionError(null);
    setTestingIds(draftNodes.map((node) => node.id));
    const request: NodeTestRequest = {};
    try {
      resource.setData(
        await apiPost<NodesResponse>("/hub/proxy/node/test", request),
      );
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
      await apiPost<NodeView>("/hub/proxy/node/add", { link });
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
      title: t(TEXT_KEYS.removeTitle, { name: node.name }),
      body: t(TEXT_KEYS.removeBody),
      confirmLabel: t(TEXT_KEYS.removeConfirm),
      onConfirm: () => void removeNode(node),
    });

  const removeNode = async (node: NodeView) => {
    setActionError(null);
    try {
      await apiPost<NodesResponse>("/hub/proxy/node/remove", {
        node_id: node.id,
      });
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
          await apiPost<NodeView>("/hub/proxy/node/set", {
            node_id: node.id,
            is_enabled: node.is_enabled,
            name: node.name,
          });
        }
      }
      if (diff.isBalancerChanged) {
        await apiPost<BalancerSettings>(
          "/hub/proxy/balancer/set",
          draftBalancer,
        );
      }
      const result = await apiPost<ApplyResult>("/hub/proxy/apply");
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
  const isTesting = testingIds.length > 0;

  return (
    // The panel owns the draft, so it draws its own frame: a parent cannot
    // know this box has unsaved changes, and the glow that says so has to come
    // from whatever holds the state.
    <div
      className={`settings_group ${isUnapplied ? "settings_group--dirty" : ""}`}
    >
      <div className="settings_group_title">
        <h2>{t(TEXT_KEYS.title)}</h2>
      </div>
      <p className="field_hint">{t(TEXT_KEYS.hint)}</p>

      {actionError !== null && (
        <div className="notice notice--error">
          <Icon name="alert" size={15} />
          <div className="notice_body">{actionError}</div>
        </div>
      )}

      <div className="nodes_toolbar">
        <div className="nodes_toolbar_group">
          <label className="field nodes_toolbar_field nodes_toolbar_field--url">
            <span className="field_label">{t(TEXT_KEYS.probeUrlLabel)}</span>
            <input
              className="input"
              value={draftBalancer?.probe_url ?? ""}
              disabled={draftBalancer === null}
              onChange={(event) => handleProbeUrlChange(event.target.value)}
            />
            <span className="field_hint">{t(TEXT_KEYS.probeUrlHint)}</span>
          </label>

          <label className="field nodes_toolbar_field nodes_toolbar_field--url">
            <span className="field_label">
              {t(TEXT_KEYS.referenceUrlLabel)}
            </span>
            <input
              className="input"
              value={draftBalancer?.reference_url ?? ""}
              disabled={draftBalancer === null}
              onChange={(event) => handleReferenceUrlChange(event.target.value)}
            />
            <span className="field_hint">{t(TEXT_KEYS.referenceUrlHint)}</span>
          </label>

          <label className="field nodes_toolbar_field">
            <span className="field_label">
              {t(TEXT_KEYS.probeIntervalLabel)}
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
            <span className="field_hint">{t(TEXT_KEYS.probeIntervalHint)}</span>
          </label>
        </div>

        {/* Panel-scope actions: adding a node and measuring every one of them
            belong to the list, not to any row in it. */}
        <div className="nodes_toolbar_actions">
          <button
            type="button"
            className="button button--primary"
            onClick={() => setIsAddOpen((open) => !open)}
          >
            <Icon name="plus" size={14} />
            {t(TEXT_KEYS.nodeAdd)}
          </button>
          <button
            type="button"
            className="button"
            onClick={() => void handleTestAll()}
            disabled={isTesting || draftNodes.length === 0}
          >
            <Icon name="bolt" size={14} />
            {isTesting ? t(TEXT_KEYS.testingAll) : t(TEXT_KEYS.testAll)}
          </button>
        </div>
      </div>

      {isAddOpen && (
        <form
          className="nodes_add"
          onSubmit={(event) => void handleAddNode(event)}
        >
          <label className="field">
            <span className="field_label">{t(TEXT_KEYS.shareLinkLabel)}</span>
            <input
              className="input"
              value={shareLink}
              placeholder="ss://… or vless://…"
              autoFocus
              onChange={(event) => setShareLink(event.target.value)}
            />
            <span className="field_hint">{t(TEXT_KEYS.shareLinkHint)}</span>
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
              {t(TEXT_KEYS.nodeAddCancel)}
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={isAdding || shareLink.trim().length === 0}
            >
              <Icon name="plus" size={14} />
              {isAdding ? t(TEXT_KEYS.nodeAdding) : t(TEXT_KEYS.nodeAddSubmit)}
            </button>
          </div>
        </form>
      )}

      <div className="nodes_summary">
        <span>{t(TEXT_KEYS.summaryEnabled, { count: enabledCount })}</span>
        <span>{t(TEXT_KEYS.summaryAlive, { count: aliveCount })}</span>
        <span>{t(TEXT_KEYS.summaryTotal, { count: draftNodes.length })}</span>
        <span>
          {t(TEXT_KEYS.summaryMoved, { bytes: formatBytes(totalTraffic) })}
        </span>
      </div>

      {resource.isLoading && draftNodes.length === 0 ? (
        <div className="nodes_grid">
          <div className="skeleton" style={{ height: SKELETON_HEIGHT }} />
          <div className="skeleton" style={{ height: SKELETON_HEIGHT }} />
          <div className="skeleton" style={{ height: SKELETON_HEIGHT }} />
        </div>
      ) : draftNodes.length === 0 ? (
        <div className="placeholder">
          <span>{t(TEXT_KEYS.empty)}</span>
          <span className="faint">{t(TEXT_KEYS.emptyHint)}</span>
        </div>
      ) : (
        <div className="nodes_grid">
          {draftNodes.map((node) => (
            <NodeCard
              key={node.id}
              node={node}
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
        label={t(TEXT_KEYS.applyLabel)}
        hint={
          isSavedNotApplied ? t(TEXT_KEYS.applyHint) : (diff?.summary ?? "")
        }
        warning={t(TEXT_KEYS.applyWarning)}
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
 * Which nodes are on, what they are called and how the hub measures them.
 * What a node is doing — alive, its two latencies, what it has moved — is the
 * gateway's answer and lands in the draft on its own, so counting it here
 * would read a measurement coming back as somebody's edit.
 */
function stagedPayload(nodes: NodeView[], balancer: BalancerSettings): string {
  return JSON.stringify([
    nodes.map((node) => [node.id, node.name, node.is_enabled]),
    balancer,
  ]);
}
