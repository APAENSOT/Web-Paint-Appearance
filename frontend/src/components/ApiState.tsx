import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { errorDetail, errorHeadline } from "@/api/error-copy";
import { AlertCircle, LoaderCircle } from "lucide-react";

export function ApiErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  const status = error instanceof ApiError ? error.status : undefined;
  const body = error instanceof ApiError ? error.body : undefined;
  const original = body?.message;
  const friendly = errorDetail(error);
  const mapped = errorHeadline(error);
  const title =
    mapped ??
    (status === 401
      ? "Authentication required"
      : status === 503
        ? "Measurement service unavailable"
        : status === 403
          ? "Action not permitted"
          : "Request unsuccessful");
  const detail =
    original && friendly !== original
      ? friendly
      : (original ??
        (status === 401
          ? "Your session could not be verified. Sign in again or contact your administrator, then retry."
          : status === 503
            ? "Measurements are temporarily unavailable. Please retry in a moment."
            : error.message.includes("VITE_API_BASE_URL")
              ? error.message
              : "We could not connect to the measurement service. Check your connection, then retry."));
  return (
    <div role="alert" className="p-6 sm:p-10">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        <AlertCircle size={20} aria-hidden="true" />
        {title}
      </h2>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">{detail}</p>
      {status && (
        <p className="mt-2 text-sm">
          HTTP {status}
          {body ? ` · ${body.error}` : ""}
        </p>
      )}
      {body?.correlationId && (
        <p className="mt-2 break-all text-xs text-muted-foreground">
          Correlation ID: {body.correlationId}
        </p>
      )}
      {original && friendly !== original && (
        <details className="mt-3 text-xs text-muted-foreground">
          <summary className="cursor-pointer py-2">Technical detail</summary>
          <p className="mt-2 whitespace-pre-wrap break-all">{original}</p>
        </details>
      )}
      {retry && (
        <Button className="mt-5" variant="outline" onClick={retry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function LoadingState({ children }: { children: React.ReactNode }) {
  return (
    <p
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 p-8 text-sm text-muted-foreground"
    >
      <LoaderCircle className="size-5 shrink-0 motion-safe:animate-spin" aria-hidden="true" />
      {children}
    </p>
  );
}
