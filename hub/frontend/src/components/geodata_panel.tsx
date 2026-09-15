import { useEffect, useState } from "react";

import { Icon } from "./icon";
import { Spinner } from "./spinner";
import { apiPost, describeError } from "../api_client";
import { t, useLanguage } from "../i18n";
import { stripAnsi } from "../strip_ansi";
import { useTaskStream } from "../use_task_stream";
import type { GeodataView, TaskStarted } from "../api_types";

import "./geodata_panel.css";

/**
 * Which release of the address and domain databases the split runs on.
 *
 * The button asks the two repositories what they publish now before it fetches
 * anything, so a box already on the newest release says so instead of
 * downloading the same two files again. An update is a task: the files are
 * fetched and checked, and xray is restarted onto them, which is the point at
 * which the split is actually using them.
 */

interface GeodataPanelProps {
  geodata: GeodataView;
  /** Called once an update has finished, so the page re-reads the releases. */
  onUpdated: () => void;
}

export function GeodataPanel({ geodata, onUpdated }: GeodataPanelProps) {
  // Redrawn when the panel's language changes.
  useLanguage();
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const task = useTaskStream(taskId);

  useEffect(() => {
    if (taskId !== null && !task.isRunning && task.exitCode !== null) {
      onUpdated();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task.isRunning, task.exitCode]);

  const update = async () => {
    setError(null);
    setNotice(null);
    setTaskId(null);
    setIsScanning(true);
    try {
      const scanned = await apiPost<GeodataView>("/hub/proxy/geodata/scan");
      if (isCurrent(scanned)) {
        setNotice(t("ui.proxy.geodata_current"));
        return;
      }
      const started = await apiPost<TaskStarted>("/hub/proxy/geodata/update");
      setTaskId(started.task_id);
    } catch (cause: unknown) {
      setError(describeError(cause));
    } finally {
      setIsScanning(false);
    }
  };

  const isBusy = isScanning || task.isRunning;

  return (
    <div className="geodata">
      <div className="geodata_head">
        <span className="geodata_releases mono">
          {`geoip ${geodata.geoip_version} · geosite ${geodata.geosite_version}`}
        </span>
        <span className="faint">
          {geodata.source === "package"
            ? t("ui.proxy.geodata_source_package")
            : t("ui.proxy.geodata_source_release")}
        </span>
        <button
          type="button"
          className="button"
          onClick={() => void update()}
          disabled={isBusy}
        >
          {isBusy ? <Spinner size={14} /> : <Icon name="download" size={14} />}
          {isScanning
            ? t("ui.proxy.geodata_scanning")
            : task.isRunning
              ? t("ui.proxy.geodata_updating")
              : t("ui.proxy.geodata_update")}
        </button>
      </div>
      {notice !== null && <span className="field_hint">{notice}</span>}
      {error !== null && <span className="field_error">{error}</span>}
      {task.error !== null && <span className="field_error">{task.error}</span>}
      {(taskId !== null || task.lines.length > 0) && (
        <pre className="geodata_log">{stripAnsi(task.lines.join("\n"))}</pre>
      )}
    </div>
  );
}

/** Whether the scan found the box already on what the repositories publish. */
function isCurrent(scanned: GeodataView): boolean {
  if (scanned.latest === null) {
    return true;
  }
  return (
    scanned.latest.geoip_version === scanned.geoip_version &&
    scanned.latest.geosite_version === scanned.geosite_version
  );
}
