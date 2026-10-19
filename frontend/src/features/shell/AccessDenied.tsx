import { Link } from "@tanstack/react-router";
import { LockKeyhole } from "lucide-react";

export function AccessDenied({
  requiredRole,
  message,
}: {
  requiredRole: "Engineer" | "Admin";
  message?: string;
}) {
  return (
    <section
      className="panel min-h-[420px] p-6 sm:p-9"
      style={{ boxShadow: "inset 0 2px 0 var(--primary)" }}
    >
      <LockKeyhole aria-hidden="true" className="mb-5 size-6 text-muted-foreground" />
      <h1 className="text-2xl font-semibold">{requiredRole} access required</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        {message ??
          (requiredRole === "Engineer"
            ? "Upload, commit and mapping require Engineer or Admin access. Explore Overview or a plant workspace."
            : "Administration requires Admin access. You can explore Overview or a plant workspace.")}
      </p>
      <Link
        to="/"
        className="mt-6 inline-flex font-medium text-primary underline underline-offset-4"
      >
        Return to Overview
      </Link>
    </section>
  );
}
