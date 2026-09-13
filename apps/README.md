# apps/

Workload manifests, reconciled after the whole infrastructure layer is Ready.

```
apps/
├── base/          environment-agnostic manifests, one directory per app
│   └── webapp/    topic 4 (cd-webapp): Django+aioquic/Hypercorn backend, Vite+nginx frontend
└── homelab/       overlay for the "homelab" cluster -- the path Flux reconciles
```

Application *source code* does not live here; it lives in `src/<app>/` at the repo
root (`src/webapp/backend`, `src/webapp/frontend`) so that CI (topic 3) builds images
from `src/` while Flux deploys the manifests from `apps/`.
