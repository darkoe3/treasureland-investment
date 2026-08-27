const statusItems = [
  { label: "Frontend", value: "Next.js App Router" },
  { label: "Backend", value: "Django REST API ready" },
  { label: "Database", value: "PostgreSQL-ready models" },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto flex min-h-screen w-full max-w-6xl flex-col justify-center px-6 py-12">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-emerald-300">
            Phase 1 foundation
          </p>
          <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white sm:text-5xl">
            Treasureland Investment Management System
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300">
            The application shell is running. Core database models, secured API
            endpoints, authentication, and seed data are prepared in the backend.
          </p>
        </div>

        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          {statusItems.map((item) => (
            <div key={item.label} className="rounded-lg border border-slate-800 bg-slate-900 p-5">
              <p className="text-sm text-slate-400">{item.label}</p>
              <p className="mt-2 text-lg font-medium text-white">{item.value}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
