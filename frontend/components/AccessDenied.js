import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { BrandLogo } from "./BrandLogo";

export default function AccessDenied() {
  return (
    <section className="access-denied">
      <BrandLogo size="inline" />
      <ShieldAlert size={32} aria-hidden="true" />
      <h2>Access denied</h2>
      <p>This area is restricted to Super Admin users.</p>
      <Link className="primary-button" href="/dashboard">Back to overview</Link>
    </section>
  );
}
