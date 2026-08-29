import Link from "next/link";
import BrandIdentity from "../components/BrandLogo";

export default function Home() {
  return (
    <main className="login-page">
      <section className="login-hero">
        <BrandIdentity variant="login" subtitle="Secure operations portal" />
        <div className="login-panel">
          <p className="eyebrow">Staff access</p>
          <h1>Treasureland Investment Limited</h1>
          <p className="login-copy">Use your administrator-issued account to manage daily operations and accountant access.</p>
          <Link className="primary-button full" href="/login">Go to secure login</Link>
        </div>
      </section>
    </main>
  );
}
