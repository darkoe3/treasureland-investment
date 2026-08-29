"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientRequest } from "../lib/client-api";

export default function LogoutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try {
      await clientRequest("/api/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button className="icon-text-button ghost" type="button" onClick={logout} disabled={busy}>
      <LogOut size={18} aria-hidden="true" />
      <span>{busy ? "Signing out" : "Logout"}</span>
    </button>
  );
}
