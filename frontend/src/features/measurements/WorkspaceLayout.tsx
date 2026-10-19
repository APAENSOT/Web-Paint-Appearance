import { useEffect, useState, type ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { ThemeToggle } from "@/components/ct/ThemeToggle";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { ActiveMode } from "@/components/ct/FilterPanel";
import { useCompactWorkspace } from "./use-compact-workspace";
import "./workspace.css";
import { useSurfaceMotion } from "@/hooks/use-surface-motion";

const LABELS: Record<ActiveMode, string> = {
  overview: "Monthly Overview",
  detail: "Monthly Detail",
  comparison: "Comparison",
  analysis: "Analysis & Report",
  data: "Data",
  standard: "Standard",
  model: "Model Detail",
};

export function WorkspaceLayout({
  code,
  active,
  domain,
  navigationKey,
  navigation,
  children,
}: {
  code: string;
  active: ActiveMode;
  domain?: string;
  navigationKey: string;
  navigation: ReactNode;
  children: ReactNode;
}) {
  const compact = useCompactWorkspace();
  const { ref: surface, ...motionEvents } = useSurfaceMotion(`${navigationKey}:${domain ?? ""}`);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    setOpen(false);
  }, [navigationKey, compact]);
  useEffect(() => {
    document.title = `${LABELS[active]} · ${code} | Paint Appearance`;
  }, [active, code]);
  return (
    <div className="workspace" {...motionEvents}>
      {compact && (
        <div className="workspace-context">
          <div className="workspace-context__actions">
            {domain && <span className="workspace-domain">{domain}</span>}
            {compact && (
              <Sheet open={open} onOpenChange={setOpen}>
                <SheetTrigger asChild>
                  <button className="workspace-menu" type="button">
                    <SlidersHorizontal size={16} /> Views & filters
                  </button>
                </SheetTrigger>
                <SheetContent side="left" className="workspace-drawer">
                  <div className="workspace-drawer__heading">
                    <SheetTitle>{code} workspace</SheetTitle>
                    <SheetDescription>
                      Choose a view, adjust filters or open settings.
                    </SheetDescription>
                  </div>
                  <div className="workspace-drawer__body">{navigation}</div>
                  <button
                    type="button"
                    className="workspace-drawer__done"
                    onClick={() => setOpen(false)}
                  >
                    Show results
                  </button>
                </SheetContent>
              </Sheet>
            )}
            <ThemeToggle />
          </div>
        </div>
      )}
      <div className="workspace-grid">
        {!compact && (
          <nav className="workspace-sidebar" aria-label="Plant views and settings">
            {navigation}
          </nav>
        )}
        <div ref={surface} className="workspace-results" id="workspace-results" tabIndex={-1}>
          {children}
        </div>
      </div>
    </div>
  );
}
