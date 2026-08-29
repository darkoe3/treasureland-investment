export default function PlaceholderPage({ title, description }) {
  return (
    <section className="panel placeholder-panel">
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}
