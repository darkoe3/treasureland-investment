import { BrandLogo } from "../../../../components/BrandLogo";

export default function NewAccountantLoading() {
  return (
    <section className="panel placeholder-panel" aria-live="polite">
      <BrandLogo size="inline" />
      <h2>Loading form</h2>
      <p>Loading active agencies for permission setup.</p>
    </section>
  );
}
