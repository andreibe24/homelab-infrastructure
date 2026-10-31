# Linkerd

Flux installs the Linkerd edge CRDs and control plane from the official Helm
repository. Both charts must be upgraded together. The cluster must be able to
reach `helm.linkerd.io` and pull images from `cr.l5d.io`; Kubernetes 1.31 or
newer is required. Cilium's socket-level service load balancing is disabled for
pods so Linkerd can perform service discovery.

The application and infrastructure Kustomizations annotate their managed
namespaces for proxy injection. New pods in those namespaces get a proxy;
existing pods are **not** restarted by a namespace annotation. The Linkerd,
cert-manager, kube-system, and flux-system namespaces are intentionally outside
this policy to avoid bootstrap dependencies. Linkerd also skips host-network
pods, including the external Envoy gateway. Namespaces created outside these
Kustomizations need their own `linkerd.io/inject: enabled` annotation.
Individual workloads may opt out with `linkerd.io/inject: disabled`. Linkerd
intercepts TCP, not UDP; injection alone does not encrypt UDP or enforce
mutual TLS for connections to unmeshed peers.

The injector defaults to failing open if its webhook is unavailable. An
unmeshed pod may therefore start during an outage and must be restarted later.
Native sidecars allow Jobs to terminate. The proxy init container requires
`NET_ADMIN` and `NET_RAW`; namespaces enforcing restricted Pod Security
standards need a Linkerd CNI deployment or an appropriate exception.

## Rollout

After Flux reports `linkerd-certificates`, `linkerd-crds`, and
`linkerd-control-plane` ready, restart existing workloads in each opted-in
namespace in a controlled order. Account for single-replica workloads and
operator-managed databases; use each operator's documented rolling restart
mechanism rather than deleting database pods indiscriminately. Check application
health and the gateway, limiter, Dragonfly, and database paths after each
restart. The limiter and Dragonfly network policies allow the proxy's
control-plane connections while retaining their application-port restrictions.
The mesh uses transparent outbound transport rather than the default transport
header, which would route traffic through port 4143 and bypass those
restrictions. Dragonfly overrides the default opaque-port configuration on its
pod and Service so Redis traffic also uses the original port. Redis uses
client-first protocol detection; idle connections may encounter Linkerd's
10-second detection timeout. Check limiter-to-Dragonfly and operator-to-admin
traffic, including denied cross-port access, before relying on the policy.

Use the Linkerd CLI matching the installed edge version to check the rollout:

```sh
linkerd check
linkerd -n whoami check --proxy
linkerd -n sample-http3 check --proxy
linkerd -n webapp-django-vite check --proxy
linkerd -n agentgateway check --proxy
```

Repeat the proxy check for the other opted-in infrastructure namespaces and
inspect any skipped or unmeshed pods. A successful control-plane check alone
does not establish that all workloads are meshed.

## Identity certificates

cert-manager creates a dedicated ECDSA trust anchor and a short-lived identity
issuer. The issuer rotates automatically; Linkerd reloads it from the
`linkerd-identity-issuer` Secret. The trust anchor has a ten-year lifetime,
renews one year before expiry, and retains its private key on renewal. Flux
reads its public certificate from the `linkerd-trust-anchor` Secret and updates
the Helm release when it changes. Restart meshed pods before the old trust
anchor expires so they pick up the renewed trust bundle.

Do not delete the trust-anchor Secret or rotate its private key in place:
that would break trust between old and new proxies. Key rotation requires a
planned overlapping trust bundle, rollout of all proxies, issuance under the
new key, and a second rollout before removal of the old anchor. The current
single-certificate Helm value does not automate that procedure. Monitor the
certificate expiry and rehearse the upstream
[trust-anchor rotation procedure](https://linkerd.io/2-edge/tasks/automatically-rotating-control-plane-tls-credentials/)
before changing it.
