import { Icon } from "./icon";
import { useLiveStats } from "../use_live_stats";

/**
 * Says so when the proxy is carrying a scope and every enabled exit is dead.
 *
 * Names resolve at the exit by design, so a dead exit is a dead resolver:
 * traffic sent to the proxy and the LAN's DNS both fail together. Without
 * this line the page looks healthy — every switch on, every card green —
 * while the network behind the box is dark, which reads as "the proxy does
 * nothing" rather than "the exit is unreachable".
 *
 * With the direct fallback on nothing is dark, and the line still has to be
 * there: traffic somebody meant to proxy is going out under this machine's
 * own address, which is worth knowing before it goes on for a week.
 */
interface DeadExitsNoticeProps {
  /** Whether the person has asked for a dead exit to fall back to direct. */
  isFallingBack?: boolean;
}

export function DeadExitsNotice({
  isFallingBack = false,
}: DeadExitsNoticeProps) {
  const { latestFrame } = useLiveStats();
  if (latestFrame === null) {
    return null;
  }
  const isScoped =
    latestFrame.proxy_scope !== "off" && latestFrame.proxy_scope !== "unused";
  const probes = latestFrame.nodes;
  const isEveryExitDead =
    probes.length > 0 && probes.every((probe) => !probe.is_alive);
  if (!isScoped || !isEveryExitDead) {
    return null;
  }
  return (
    <div className={`notice notice--${isFallingBack ? "warn" : "error"}`}>
      <Icon name="alert" size={15} />
      <div className="notice_body">
        {isFallingBack
          ? "Every enabled exit node is unreachable, so traffic sent to the proxy is leaving through the WAN instead, under this machine's own address."
          : "Every enabled exit node is unreachable. Traffic sent to the proxy (the LAN's names included) fails until one answers."}
      </div>
    </div>
  );
}
