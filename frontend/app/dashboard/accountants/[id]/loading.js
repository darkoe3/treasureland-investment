import { BrandLogo } from "../../../../components/BrandLogo";

export default function AccountantDetailLoading() {
  return (
    <section className="panel placeholder-panel" aria-live="polite">
      <BrandLogo size="inline" />
      <h2>Loading accountant</h2>
      <p>Loading account details and agency permissions.</p>
    </section>
  );
}
