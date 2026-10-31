# Monitoring

The kube-prometheus-stack provides Prometheus, Grafana, Alertmanager, Kubernetes dashboards, and its default alert rules for pod crash loops, node readiness, and filesystem capacity. Additional rules alert when a container is OOM-killed or a pod's readiness or liveness probe fails. Alerts are labeled with `cluster: dev`, which is included in the Slack message title.

In dev, Grafana is available at `https://grafana.localhost:8443` and offers
Keycloak sign-in when the identity resources are ready. See
[Keycloak and central sign-in](keycloak.md) for user provisioning and roles.
The chart-generated local administrator remains available for recovery; its
password is stored in the `monitoring-grafana` Secret in the `monitoring`
namespace. Homelab does not yet have OIDC configured.

Before Slack notifications can be delivered, edit `stringData.slack_api_url` in `clusters/dev/init-manifests/secrets/alertmanager-slack.secret.yaml` with SOPS and set it to the incoming webhook URL for the desired Slack channel. Do not commit the webhook URL in plaintext.
