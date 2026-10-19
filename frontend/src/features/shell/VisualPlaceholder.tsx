import type { ReactNode } from "react";

export function WorkspaceHeading({ title, description }: { title: string; description: string }) {
  return (
    <header className="px-1 pb-1">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      <div className="rule-gradient mt-3" />
    </header>
  );
}

export function VisualPlaceholder({
  title,
  reason,
  children,
}: {
  title: string;
  reason: string;
  children?: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="panel flex min-h-[420px] flex-col overflow-hidden"
      style={{
        background: "linear-gradient(180deg, var(--primary-soft), var(--panel) 30%)",
        boxShadow: "inset 0 2px 0 var(--primary), var(--shadow-panel)",
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <span className="eyebrow">Not wired this phase</span>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-12 text-center">
        <span aria-hidden="true" className="h-8 w-px bg-primary/50" />
        <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">{reason}</p>
        {children}
      </div>
    </section>
  );
}
