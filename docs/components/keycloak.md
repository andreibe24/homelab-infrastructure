# Keycloak and central sign-in

The dev cluster deploys the upstream Keycloak operator, a single Keycloak
instance, and a single CloudNativePG database in `keycloak`. This is a
development configuration, not a highly available or production-ready
identity service. The homelab cluster remains unchanged and needs its own
storage, DNS, issuer, PKI, SOPS recipient, secrets and deployment before using
central sign-in.

The `homelab` realm supplies OIDC accounts for Grafana and Campfire. The
operator's one-time RealmImport creates both confidential clients; it does
not reconcile subsequent realm or client changes. User self-registration and
password grants are disabled. The operator creates its initial administrator
Secret as `keycloak/keycloak-initial-admin`. Access the admin console at
`https://identity.localhost:8443/admin/` after trusting the dev gateway CA.
Retrieve the bootstrap credentials securely with Kubernetes access, replace
the temporary administrator with a managed administrator, and enable MFA.
Do not store or share the credentials.

Create users in the `homelab` realm, including an email address for Grafana.
Assign the `grafana-admin` realm role only to administrators; other users
receive Grafana Viewer. Grafana retains its chart-generated local administrator
as a break-glass account. Its Secret is `monitoring/monitoring-grafana`.
Keycloak account creation does not automatically grant Django staff or
superuser permissions.

## Endpoints and trust

Browsers use the gateway at `https://identity.localhost:8443`. Its wildcard
certificate uses the dev cert-manager root CA, which must be trusted by the
browser. The operator's internal HTTPS service uses a separate CA and the
DNS name `keycloak-service.keycloak.svc.cluster.local`. Grafana and Campfire
trust the public certificate in their `identity-ca` ConfigMaps; neither
disables TLS verification. Grafana's OAuth HTTP client and its separate JWKS
HTTP client both use that CA. This avoids resolving `*.localhost` inside pods.
The signing key and OIDC client secrets are SOPS-encrypted for dev and
reflected only to the namespaces that need them.

The gateway sends HTTP to Keycloak after external TLS termination. Keycloak
accepts forwarded headers, so its operator-managed HTTP policy permits only
the gateway namespace. Internal HTTPS is limited to the Keycloak, monitoring,
and Campfire namespaces. Those namespaces are trusted: a compromised pod
there can reach Keycloak and send forwarded headers. Review this boundary,
gateway host-network behavior, RBAC, and network policies before any
multi-node or production deployment.

## Campfire rollout and account migration

The dev `campfire-oidc` Secret enables OIDC when the new application image
reads it. Existing pinned images do not contain this code. After the
application release is built, update **both** backend and frontend image tags
and digests together, following the normal Renovate release process. Until
then, the existing application continues to use local accounts.

OIDC identities are bound by the exact issuer and immutable Keycloak user ID
(`sub`), never by username or email. New identities create separate Django
users; existing forum posts remain attached to their original users. To
preserve an existing account, before its first OIDC login an administrator
must verify the user's Keycloak ID in the admin console and explicitly link it
to the existing Django username. With the new backend image deployed:

```sh
kubectl -n webapp-django-vite exec deploy/webapp-django-vite-backend -- \
  python manage.py link_oidc_user --username EXISTING_DJANGO_USERNAME \
  --issuer https://identity.localhost:8443/realms/homelab --subject KEYCLOAK_USER_ID
```

The command refuses an already-linked user or subject. If a user already
signed in and a new Django account was created, investigate and migrate the
data deliberately; the command will not merge accounts. New OIDC users use the
Keycloak preferred username if it is valid and available, otherwise an opaque
identifier, and have no usable local password. Usernames are not automatically
changed if the Keycloak username changes. In OIDC mode the local
login and registration APIs are disabled, and Django sessions expire after
one hour. Signing out of Campfire ends its local session, not the Keycloak
session; disabling a Keycloak account does not immediately revoke an existing
Campfire session. MCP's bearer token and agentgateway API keys remain
separate machine credentials.

## Operations

The database has one instance and no configured backup. Establish and test
database backups, restore procedures, storage capacity and recovery of the
dev SOPS age key before depending on these accounts. Protect the age key:
losing it prevents recovery of the encrypted client secrets and internal CA
private key. Do not copy the dev identity CA or credentials to homelab.

The internal CA certificate is committed as public ConfigMaps and expires
after ten years; its private key is in `identity-ca.secret.yaml`. Rotate the
CA before expiry by securely creating a new CA and encrypted Secret, updating
both public ConfigMaps, and coordinating certificate reissuance and client
rollouts. Keep old and new trust during transition. The server certificate is
renewed by cert-manager. Do not expose the CA private key to application
namespaces.

Client secrets are in `campfire-oidc.secret.yaml` and
`grafana-oidc.secret.yaml`. Since RealmImport is creation-only, editing an
encrypted Secret does **not** rotate the corresponding Keycloak client.
Coordinate client secret changes in the Keycloak admin console and the SOPS
Secret, restart consumers as needed, and verify login; plan for a brief outage.
Do not re-run the import expecting it to update an existing realm.

The operator bundle is pinned in the dev operator Kustomization and is
Renovate-managed with manual review. Its matching Keycloak image is selected
by the upstream operator bundle. Before upgrading, review Keycloak migration
notes, check database compatibility, and verify backups. CRDs and operator
resources use `prune: false`; deleting the registration does not uninstall
them automatically. The Keycloak namespace is also protected from Flux
pruning, but deleting it manually destroys namespaced workloads and may
destroy database storage depending on its storage class.

After reconciliation, verify the `keycloak-operator`, `keycloak`, and
`identity-trust` Flux Kustomizations; the database, Keycloak and RealmImport
conditions; the browser certificate; both OIDC logins; Grafana role mapping;
and Campfire account linking and logout. Do not assume rendered YAML alone
proves that sign-in works.
