"use client";

import Link from "next/link";
import { Plus, Search } from "lucide-react";
import { useMemo, useState } from "react";

export default function AccountantsClient({ initialAccountants }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState("all");

  const accountants = useMemo(() => {
    return initialAccountants.filter((accountant) => {
      const matchesQuery = `${accountant.full_name} ${accountant.email}`.toLowerCase().includes(query.toLowerCase());
      const matchesActive = active === "all" || String(accountant.is_active) === active;
      return matchesQuery && matchesActive;
    });
  }, [initialAccountants, query, active]);

  return (
    <div className="page-stack">
      <div className="toolbar">
        <div className="search-box">
          <Search size={18} aria-hidden="true" />
          <label className="sr-only" htmlFor="accountant-search">Search accountants</label>
          <input id="accountant-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name or email" />
        </div>
        <select aria-label="Filter accountants by status" value={active} onChange={(event) => setActive(event.target.value)}>
          <option value="all">All statuses</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </select>
        <Link className="primary-button" href="/dashboard/accountants/new">
          <Plus size={18} aria-hidden="true" />
          <span>New Accountant</span>
        </Link>
      </div>

      <div className="panel">
        <div className="table-wrap responsive-table">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Assigned Agencies</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {accountants.map((accountant) => (
                <tr key={accountant.id}>
                  <td data-label="Name">{accountant.full_name}</td>
                  <td data-label="Email">{accountant.email}</td>
                  <td data-label="Assigned Agencies">
                    {accountant.agency_assignments?.map((item) => item.agency.name).join(", ") || "None"}
                  </td>
                  <td data-label="Status"><span className={accountant.is_active ? "status-pill approved" : "status-pill returned"}>{accountant.is_active ? "Active" : "Inactive"}</span></td>
                  <td data-label="Action"><Link className="text-link" href={`/dashboard/accountants/${accountant.id}`}>View/Edit</Link></td>
                </tr>
              ))}
              {!accountants.length ? (
                <tr><td colSpan="5" className="empty-cell">No accountants match the current filters.</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
