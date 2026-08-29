import { Suspense } from "react";
import BrandIdentity from "../../components/BrandLogo";
import LoginForm from "../../components/LoginForm";

export const metadata = {
  title: "Login | Treasureland Investment Limited",
};

export default function LoginPage() {
  return (
    <main className="login-page">
      <section className="login-hero" aria-label="Treasureland secure login">
        <BrandIdentity variant="login" subtitle="Daily operations and accountant access" />
        <Suspense fallback={<div className="login-panel">Loading secure login...</div>}>
          <LoginForm />
        </Suspense>
      </section>
    </main>
  );
}
