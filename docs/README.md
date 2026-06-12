# docs/

- **`design/`** — design docs for big tasks (the per-feature contract: exit criteria, interaction map,
  test plan). Created before building a large feature; reconciled to code before merge.
- **`features/`** — one short doc per built feature (written by the /build loop).
- **`deploy/`** — deployment guides (M3.3: [Azure Container Apps](deploy/azure-container-apps.md);
  the container itself is cloud-neutral — see the root `Dockerfile`).

The product spine itself (`PRODUCT.md`) and the codebase map (`STRUCTURE.md`) live at the repo root so
the playbook and newcomers find them immediately.
