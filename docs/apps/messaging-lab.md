# Messaging lab

Messaging lab is a private command-line application for experimenting with a
dedicated Dragonfly instance and a RabbitMQ tenant. It has no HTTP endpoint.
Its Kubernetes Deployment runs an idle container so an authorized operator can
run the exercises with `kubectl exec`. Access to `pods/exec` is privileged:
the container can read the lab's credentials and communicate with both stores.

## Prerequisites and deployment

The dev cluster reconciles the app through `apps/`. The app waits for the
Dragonfly operator, RabbitMQ, Reflector, and the dev `flux-system/secrets`
Kustomization. The dev Dragonfly password is SOPS-encrypted and reflected only
to `messaging-lab`. RabbitMQ's topology operator generates a separate user and
password in `messaging-lab-user-credentials`; the app never uses the broker's
administrator credentials.

The image workflow builds the app on pull requests and publishes
`ghcr.io/andreibe24/homelab-infrastructure/messaging-lab:main` and a commit-SHA
tag on pushes to `main`. Make that GHCR package public, or provision a suitable
image pull secret before reconciliation. The `main` tag bootstraps the first
image before a digest exists; after publication, pin its digest in the
Deployment and let Renovate maintain it. Subsequent source changes need a new
digest in the manifest (or, while using the mutable tag, a rollout restart).
Flux may initially report the Deployment as not ready until the image is
published and the topology is reconciled.

The homelab shared roots are currently suspended. Before enabling this app
there, provision a **different** Dragonfly password and a SOPS recipient and
`flux-system/secrets` reconciliation for that cluster; do not copy the dev
secret or key. Review storage, certificate trust, networking, package access,
and the RabbitMQ single-node limitation first. See [secrets](../secrets.md)
and [Talos bootstrap](../homelab-talos.md).

## Exercises

Once the Deployment is ready, run:

```sh
kubectl -n messaging-lab exec deploy/messaging-lab -- python /app/lab.py cache-put greeting hello --ttl 60
kubectl -n messaging-lab exec deploy/messaging-lab -- python /app/lab.py cache-get greeting
kubectl -n messaging-lab exec deploy/messaging-lab -- python /app/lab.py count
kubectl -n messaging-lab exec deploy/messaging-lab -- python /app/lab.py publish hello
kubectl -n messaging-lab exec deploy/messaging-lab -- python /app/lab.py consume
```

Wait for the TTL and repeat `cache-get` to see a miss; repeat `count` to see an
atomic increment. Publishing uses a persistent message, a unique ID, publisher
confirms and mandatory routing. `consume` fetches one message and acknowledges
only after printing it. Delivery is **at least once**: interruption after
printing but before acknowledgement may cause redelivery. A real consumer must
make its side effects idempotent. Jobs without an ID or with invalid UTF-8 are
rejected to `lab.dead`; output errors are requeued. The jobs and dead-letter
queues are bounded at 1,000 messages and 10 MiB each. Quorum dead-lettering is
configured for at-least-once transfer; if the dead-letter queue fills, rejected
jobs remain in the source queue and publishing can eventually be rejected.
Investigate and drain dead letters with an authorized RabbitMQ administrator.

Dragonfly snapshots to a 1 GiB PVC every five minutes; recent writes can be
lost between snapshots. RabbitMQ has one replica and a 2 GiB PVC. These are
learning defaults, not highly available or backup solutions. Queue and vhost
resources use `deletionPolicy: retain`; deleting the app does not constitute a
backup and requires deliberate cleanup of retained RabbitMQ objects and PVCs.
Queue arguments are immutable; changing them for an existing retained queue
requires an explicit migration or recreation after preserving any data.

## Security and operations

Both data connections use TLS with hostname verification and the cert-manager
root CA. The app only mounts the public CA certificate, not the Dragonfly
server's private key. RabbitMQ permits the lab identity to publish only to
`lab.events` and read only `lab.jobs`; it cannot configure topology or access
other vhosts. NetworkPolicies restrict data ports to the lab and the Dragonfly
admin port to the operator. RabbitMQ operator admission webhooks retain the
infrastructure namespace's baseline ingress; RabbitMQ itself is excluded from
that broader policy. RabbitMQ egress permits DNS and TCP 443/6443 to Cilium's
`kube-apiserver` entity for Kubernetes peer discovery.

The lab and RabbitMQ pods explicitly opt out of Linkerd injection because
their own TLS protects data traffic and webhook/peer discovery do not use
Linkerd. These policies assume Cilium enforcement; review host-network and
control-plane traffic on other clusters. Do not expose broker management or
the app publicly. Inspect reconciliation and readiness with:

```sh
kubectl -n rabbitmq get rabbitmqcluster,deploy,pods
kubectl -n messaging-lab get dragonfly,vhost,user,permission,exchange,queue,binding,deploy,pods
kubectl -n messaging-lab describe kustomization messaging-lab
```

Credentials are mounted as files. The app reloads them for each command;
Reloader restarts it when its Secrets change. Dragonfly reads its password at
startup: coordinate a password rotation and restart its StatefulSet after the
reflected Secret is updated. Certificate and CA rotation should be followed by
checking both services and restarting affected workloads; in particular, the
topology operator mounts the CA using `subPath` and needs a restart after CA
rotation.

For local development, install `src/messaging-lab/requirements.txt` in a
virtual environment and run `python src/messaging-lab/lab.py --help`. Set
`REDIS_URL` and `AMQP_URL` using credentials provisioned outside Git, plus
`REDIS_CA_FILE` or `AMQP_CA_FILE` for private CAs. TLS is required by default
(`rediss://` and `amqps://`). Only for an isolated local experiment without
TLS, explicitly set `LAB_ALLOW_INSECURE=1`. Do not paste credentials into shell
history or commit them. Local RabbitMQ must have the topology and permissions
listed above before publishing or consuming.
