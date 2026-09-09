/**
 * The machines that reach the hub as clients.
 *
 * A client is a machine pointed at this hub for its proxy, its AI endpoint
 * and its shares, whether or not the hub manages anything on it. The list and
 * what it can do arrive with the client itself; until then the page says what
 * it will hold.
 */

const WORDING = {
  title: "Clients",
  empty: "No clients yet",
  emptyHint: "Machines that connect to this hub as clients are listed here.",
};

export function ClientsPage() {
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
