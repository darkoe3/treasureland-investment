"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Building2,
  CalendarDays,
  ClipboardList,
  FileClock,
  FileText,
  Home,
  Menu,
  Settings,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import BrandIdentity from "./BrandLogo";
import LogoutButton from "./LogoutButton";

const superAdminItems = [
  { label: "Overview", href: "/dashboard", icon: Home },
  { label: "Daily Sheets", href: "/dashboard/daily-sheets", icon: ClipboardList },
  { label: "People & TPM Codes", href: "/dashboard/people", icon: Users },
  { label: "Game Schedule", href: "/dashboard/game-schedule", icon: CalendarDays },
  { label: "Agencies", href: "/dashboard/agencies", icon: Building2 },
  { label: "Accountants", href: "/dashboard/accountants", icon: ShieldCheck },
  { label: "Audit Log", href: "/dashboard/audit-log", icon: FileClock },
  { label: "Reports", href: "/dashboard/reports", icon: BarChart3 },
  { label: "Settings", href: "/dashboard/settings", icon: Settings },
];

function accountantItems(user) {
  const canReport = user.agency_assignments?.some((item) => item.can_export);
  const canHistory = user.agency_assignments?.some((item) => item.can_view_history);
  return [
    { label: "Overview", href: "/dashboard", icon: Home },
    { label: "Daily Sheets", href: "/dashboard/daily-sheets", icon: ClipboardList },
    { label: "New Daily Sheet", href: "/dashboard/daily-sheets/new", icon: FileText },
    { label: "Assigned Agencies", href: "/dashboard/assigned-agencies", icon: Building2 },
    ...(canReport ? [{ label: "Reports", href: "/dashboard/reports", icon: BarChart3 }] : []),
    ...(canHistory ? [{ label: "History", href: "/dashboard/history", icon: FileClock }] : []),
  ];
}

function titleFromPath(pathname) {
  if (pathname === "/dashboard") {
    return "Overview";
  }
  const parts = pathname.split("/").filter(Boolean).slice(1);
  return parts.map((part) => part.replace(/-/g, " ")).join(" / ") || "Dashboard";
}

function Navigation({ items, pathname, onNavigate }) {
  return (
    <nav className="dashboard-nav" aria-label="Dashboard navigation">
      {items.map((item) => {
        const Icon = item.icon;
        const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
        return (
          <Link key={item.href} href={item.href} className={active ? "nav-link active" : "nav-link"} onClick={onNavigate}>
            <Icon size={18} aria-hidden="true" />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export default function DashboardShell({ user, children }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const items = useMemo(() => (user.role === "SUPER_ADMIN" ? superAdminItems : accountantItems(user)), [user]);
  const pageTitle = titleFromPath(pathname);

  return (
    <div className="dashboard-frame">
      <aside className="dashboard-sidebar">
        <BrandIdentity subtitle="Investment operations" />
        <Navigation items={items} pathname={pathname} />
      </aside>

      {open ? (
        <div className="mobile-overlay" role="presentation" onClick={() => setOpen(false)}>
          <aside className="mobile-drawer" onClick={(event) => event.stopPropagation()}>
            <div className="drawer-top">
              <BrandIdentity variant="mobile" subtitle="Secure operations" />
              <button className="icon-button" type="button" onClick={() => setOpen(false)} aria-label="Close navigation">
                <X size={20} aria-hidden="true" />
              </button>
            </div>
            <Navigation items={items} pathname={pathname} onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      ) : null}

      <div className="dashboard-main">
        <header className="dashboard-header">
          <button className="icon-button mobile-menu-button" type="button" onClick={() => setOpen(true)} aria-label="Open navigation">
            <Menu size={21} aria-hidden="true" />
          </button>
          <div className="page-heading">
            <p className="breadcrumb">Dashboard / {pageTitle}</p>
            <h1>{pageTitle}</h1>
          </div>
          <div className="user-cluster">
            <div className="user-chip">
              <span>{user.full_name}</span>
              <small>{user.role === "SUPER_ADMIN" ? "Super Admin" : "Accountant"}</small>
            </div>
            <LogoutButton />
          </div>
        </header>
        <main className="dashboard-content">{children}</main>
      </div>
    </div>
  );
}
