export function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="grid gap-2">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="text-muted-foreground text-sm">Coming in the next steps.</p>
    </section>
  );
}

export function NotFoundPage() {
  return (
    <section className="grid gap-2">
      <h1 className="text-2xl font-semibold tracking-tight">Not found</h1>
      <p className="text-muted-foreground text-sm">This page does not exist.</p>
    </section>
  );
}
