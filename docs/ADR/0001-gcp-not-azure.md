# ADR 0001 — Target cloud is GCP, not Azure

**Status:** Accepted  
**Date:** 2026-09-07  
**Supersedes:** `Paint Appearance/docs/00-ARCHITECTURE.md` decision D2 (Azure)

## Context

The 2026-08-19 architecture targeted Azure because the original data source was SharePoint (Microsoft Graph) and the company already runs Entra ID. IT subsequently required:

1. Deployment on **Google Cloud Platform exclusively**.
2. **No outbound SharePoint pull** — the application may not call Graph to fetch files.

Identity remains Ford ID / Entra. Hosting and identity are therefore different vendors.

## Decision

Host on GCP: Cloud Run, Cloud SQL for PostgreSQL, Cloud Storage, Secret Manager, Artifact Registry, Cloud Logging/Monitoring. Identity stays Entra OIDC. The two are connected by a standard OIDC federation, not by co-location.

## Consequences

- Azure-specific services (Container Apps, Blob, Key Vault, Managed Identity, Application Insights, Bicep) are out of scope.
- `Sites.Selected` Graph permission is no longer needed for this product.
- Ford ID / Entra still requires an app registration — that IT request remains, but it is identity-only.
- Local Docker Compose mirrors GCP topology (postgres + api + worker + static web), not Azure.

## Alternatives rejected

- Stay on Azure despite IT: not an option after the IT decision.
- Dual-cloud portable abstractions everywhere: extra complexity for one approved cloud. Compose + Terraform for GCP is enough.
