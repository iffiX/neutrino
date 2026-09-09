/**
 * Files on a managed machine.
 *
 * Browsing and moving files runs over the same agent channel the terminals
 * do, so the page opens on a machine the way every other Agent-group page
 * does. The browser itself arrives with that channel.
 */

const WORDING = {
  title: "Files",
  empty: "No machine to browse yet",
  emptyHint: "A machine running the agent can have its files browsed here.",
};

export function FilesPage() {
  return (
    <div className="page">
      <div className="page_header">
        <div className="page_title_row">
          <h1>{WORDING.title}</h1>
        </div>
      </div>

      <div className="placeholder">
        <span>{WORDING.empty}</span>
        <span className="faint">{WORDING.emptyHint}</span>
      </div>
    </div>
  );
}
