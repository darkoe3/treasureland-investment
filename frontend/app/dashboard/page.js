import Link from "next/link";
import { redirect } from "next/navigation";
import { CalendarDays, ClipboardList, ShieldCheck, Users } from "lucide-react";
import { authenticatedBackendRequest, safeCurrentUser } from "../../lib/server-api";

export const dynamic = "force-dynamic";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

async function loadOverview(user) {
  const today = todayIso();
  const [agencies, games, sheets, accountants, tpmCodes] = await Promise.all([
    authenticatedBackendRequest("/agencies/").catch(() => []),
    authenticatedBackendRequest(`/games/for-date/?date=${today}`).catch(() => []),
    authenticatedBackendRequest(`/daily-sheets/?date=${today}`).catch(() => []),
    user.role === "SUPER_ADMIN" ? authenticatedBackendRequest("/accountants/").catch(() => []) : Promise.resolve([]),
    user.role === "SUPER_ADMIN" ? authenticatedBackendRequest("/tpm-codes/").catch(() => []) : Promise.resolve([]),
  ]);
  return { today, agencies: agencies.results || agencies, games: games.results || games, sheets: sheets.results || sheets, accountants: accountants.results || accountants, tpmCodes: tpmCodes.results || tpmCodes };
}

function StatusPill({ status }) {
  return <span className={`status-pill ${status ? status.toLowerCase() : "empty"}`}>{status || "Not started"}</span>;
}

export default async function DashboardOverview() {
  const user = await safeCurrentUser();
  if (!user) {
    redirect("/login?next=/dashboard");
  }
  const data = await loadOverview(user);
  const assigned = user.role === "ACCOUNTANT" ? user.agency_assignments.map((item) => item.agency) : data.agencies;

  return (
    <div className="page-stack">
      <section className="metric-grid" aria-label="Dashboard metrics">
        <div className="metric-card">
          <ShieldCheck size={21} aria-hidden="true" />
          <p>Accountants</p>
          <strong>{user.role === "SUPER_ADMIN" ? data.accountants.length : user.agency_assignments.length}</strong>
        </div>
        <div className="metric-card">
          <Users size={21} aria-hidden="true" />
          <p>Active TPM Codes</p>
          <strong>{user.role === "SUPER_ADMIN" ? data.tpmCodes.filter((item) => item.is_active).length : "Assigned"}</strong>
        </div>
        <div className="metric-card">
          <CalendarDays size={21} aria-hidden="true" />
          <p>Today&apos;s Games</p>
          <strong>{data.games.length}</strong>
        </div>
        <div className="metric-card">
          <ClipboardList size={21} aria-hidden="true" />
          <p>Sheets Today</p>
          <strong>{data.sheets.length}</strong>
        </div>
      </section>

      <section className="content-grid">
        <div className="panel">
          <div className="panel-heading">
            <h2>{user.role === "SUPER_ADMIN" ? "Agency Status" : "Assigned Agencies"}</h2>
            <span>{data.today}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Agency</th>
                  <th>Code</th>
                  <th>Today&apos;s Sheet</th>
                </tr>
              </thead>
              <tbody>
                {assigned.map((agency) => {
                  const sheet = data.sheets.find((item) => item.agency === agency.id);
                  return (
                    <tr key={agency.id}>
                      <td>{agency.name}</td>
                      <td>{agency.code}</td>
                      <td><StatusPill status={sheet?.status} /></td>
                    </tr>
                  );
                })}
                {!assigned.length ? (
                  <tr><td colSpan="3" className="empty-cell">No agencies available.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-heading">
            <h2>Today&apos;s Scheduled Games</h2>
            <span>{data.games.length} scheduled</span>
          </div>
          <div className="list-stack">
            {data.games.map((game) => (
              <div className="list-row" key={game.id}>
                <strong>{game.game_name}</strong>
                <span>{game.closing_time} close / {game.draw_time} draw</span>
              </div>
            ))}
            {!data.games.length ? <p className="empty-state">No games are scheduled for today.</p> : null}
          </div>
        </div>
      </section>

      {user.role === "ACCOUNTANT" ? (
        <section className="panel">
          <div className="panel-heading">
            <h2>Permission Summary</h2>
            <Link className="text-link" href="/dashboard/daily-sheets">Daily sheets</Link>
          </div>
          <div className="permission-grid">
            {user.agency_assignments.map((assignment) => (
              <div className="permission-card" key={assignment.agency.id}>
                <strong>{assignment.agency.name}</strong>
                <p>{["can_create", "can_edit", "can_delete", "can_export", "can_view_history"].filter((flag) => assignment[flag]).map((flag) => flag.replace("can_", "").replace("_", " ")).join(", ") || "Read access only"}</p>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="shortcut-row" aria-label="Super Admin shortcuts">
          <Link href="/dashboard/accountants">Manage Accountants</Link>
          <Link href="/dashboard/daily-sheets">Review Daily Sheets</Link>
          <Link href="/dashboard/game-schedule">Game Schedule</Link>
        </section>
      )}
    </div>
  );
}
