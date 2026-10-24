# Monitoring

The kube-prometheus-stack provides Prometheus, Grafana, Alertmanager, Kubernetes dashboards, and its default alert rules for pod crash loops, node readiness, and filesystem capacity. Additional rules alert when a container is OOM-killed or a pod's readiness or liveness probe fails. Alerts are labeled with `cluster: dev`, which is included in the Slack message title.

Grafana is available at `https://grafana.localhost`. The chart generates an admin password on installation and stores it in the `monitoring-grafana` Secret in the `monitoring` namespace.

Before Slack notifications can be delivered, set `stringData.slack_api_url` in `alertmanager-slack.secret.yaml` to the incoming webhook URL for the desired Slack channel, then encrypt the file with SOPS before applying it. Do not commit the webhook URL in plaintext.
