import { BrandLogo } from "../../../components/BrandLogo";

export default function AccountantsLoading() {
  return (
    <section className="panel placeholder-panel" aria-live="polite">
      <BrandLogo size="inline" />
      <h2>Loading accountants</h2>
      <p>Preparing accountant records and agency permissions.</p>
    </section>
  );
}
