#!/usr/bin/env ruby
require "open3"
require "yaml"

root = File.expand_path("../..", __dir__)
kustomize = ENV["KUSTOMIZE"]

def build(root, path, kustomize)
  command = kustomize ? [kustomize, "build", path] : ["kubectl", "kustomize", path]
  output, status = Open3.capture2e(*command, chdir: root)
  abort output unless status.success?
  YAML.load_stream(output).compact
end

def assert(condition, message)
  abort message unless condition
end

def resource(resources, kind, name)
  resources.find { |item| item["kind"] == kind && item.dig("metadata", "name") == name } ||
    abort("Missing #{kind}/#{name}")
end

app = build(root, "apps/messaging-lab", kustomize)
broker = build(root, "infrastructure/components/rabbitmq", kustomize)
registrations = build(root, "apps", kustomize) + build(root, "infrastructure/components", kustomize)

dependencies = resource(registrations, "Kustomization", "messaging-lab").dig("spec", "dependsOn")
[
  { "name" => "rabbitmq", "namespace" => "rabbitmq" },
  { "name" => "dragonfly-operator", "namespace" => "redis-operator" },
  { "name" => "secrets", "namespace" => "flux-system" },
  { "name" => "reflector", "namespace" => "reflector" }
].each do |dependency|
  assert(dependencies.include?(dependency), "Application is missing dependency #{dependency}")
end
cluster = resource(broker, "RabbitmqCluster", "rabbitmq")
assert(cluster.dig("metadata", "namespace") == "rabbitmq" &&
       cluster.dig("metadata", "annotations", "rabbitmq.com/topology-allowed-namespaces") == "messaging-lab" &&
       cluster.dig("spec", "tls", "disableNonTLSListeners") == true,
       "RabbitMQ must allow only the lab tenant and require TLS")
broker_policy = resource(broker, "NetworkPolicy", "rabbitmq")
assert(broker_policy.dig("spec", "podSelector", "matchLabels") == {
  "app.kubernetes.io/component" => "rabbitmq", "app.kubernetes.io/name" => "rabbitmq"
}, "Broker policy must select broker pods")
ingress = broker_policy.dig("spec", "ingress")
assert(ingress.size == 2 &&
       ingress.any? { |rule| rule["from"] == [{
         "namespaceSelector" => { "matchLabels" => { "kubernetes.io/metadata.name" => "messaging-lab" } },
         "podSelector" => { "matchLabels" => { "app" => "messaging-lab" } }
       }] && rule["ports"] == [{ "protocol" => "TCP", "port" => 5671 }] } &&
       ingress.any? { |rule| rule["from"] == [{
         "podSelector" => { "matchLabels" => { "app.kubernetes.io/name" => "messaging-topology-operator" } }
       }] && rule["ports"] == [{ "protocol" => "TCP", "port" => 15671 }] },
       "Broker must only accept TLS client and topology operator traffic")
api_policy = resource(broker, "CiliumNetworkPolicy", "rabbitmq-api-server")
assert(api_policy.dig("spec", "endpointSelector", "matchLabels") == broker_policy.dig("spec", "podSelector", "matchLabels") &&
       api_policy.dig("spec", "egress").all? { |rule| rule["toEntities"] == ["kube-apiserver"] } &&
       api_policy.dig("spec", "egress").flat_map { |rule| rule.fetch("toPorts", []).flat_map { |ports| ports.fetch("ports", []) } } ==
         [{ "port" => "443", "protocol" => "TCP" }, { "port" => "6443", "protocol" => "TCP" }],
       "Broker API access must be restricted to the Cilium API-server entity")
broker.select { |item| item["kind"].end_with?("WebhookConfiguration") }.each do |webhook|
  assert(webhook.dig("metadata", "annotations", "cert-manager.io/inject-ca-from").start_with?("rabbitmq/"),
         "Webhook CA must reference the renamed namespace")
  assert(webhook.fetch("webhooks").all? { |entry| entry.dig("clientConfig", "service", "namespace") == "rabbitmq" },
         "Webhook service must use the renamed namespace")
end
broker.select { |item| item["kind"] == "Certificate" }.each do |cert|
  assert(cert.dig("spec", "dnsNames").to_a.all? { |name| name.include?(".rabbitmq.svc") },
         "Certificate DNS names must use the RabbitMQ namespace")
end
operator = resource(broker, "Deployment", "messaging-topology-operator")
container = operator.dig("spec", "template", "spec", "containers").find { |item| item["name"] == "manager" }
assert(container.fetch("volumeMounts").any? { |item| item["name"] == "broker-ca" },
       "Topology operator must trust the broker CA")
app.select { |item| item["apiVersion"] == "rabbitmq.com/v1beta1" }.each do |item|
  assert(item.dig("spec", "rabbitmqClusterReference") == { "name" => "rabbitmq", "namespace" => "rabbitmq" },
         "#{item['kind']} must target the shared RabbitMQ")
end
permission = resource(app, "Permission", "messaging-lab")
assert(permission.dig("spec", "permissions") == {
  "configure" => "^$", "write" => "^lab\\.events$", "read" => "^lab\\.jobs$"
}, "Tenant permissions must be restricted")
queue = resource(app, "Queue", "messaging-lab-jobs")
assert(queue.dig("spec", "type") == "quorum" &&
       queue.dig("spec", "arguments", "x-dead-letter-routing-key") == "lab.dead" &&
       queue.dig("spec", "arguments", "x-dead-letter-strategy") == "at-least-once",
       "Jobs must be durable and have a dead-letter destination")
dragonfly = resource(app, "Dragonfly", "messaging-lab-dragonfly")
assert(dragonfly.dig("spec", "authentication", "passwordFromSecret", "name") == "messaging-lab-dragonfly" &&
       dragonfly.dig("spec", "tlsSecretRef", "name") == "messaging-lab-dragonfly-tls",
       "Dragonfly must require authentication and TLS")
deployment = resource(app, "Deployment", "messaging-lab")
assert(deployment.dig("spec", "template", "spec", "automountServiceAccountToken") == false,
       "The lab client must not have a Kubernetes API token")
ca = deployment.dig("spec", "template", "spec", "volumes").find { |volume| volume["name"] == "ca" }
assert(ca.dig("secret", "items") == [{ "key" => "ca.crt", "path" => "ca.crt" }],
       "The client must not mount the Dragonfly server private key")
secret = YAML.load_file(File.join(root, "clusters/dev/init-manifests/secrets/messaging-lab-dragonfly.secret.yaml"))
assert(secret.dig("stringData", "password").start_with?("ENC[") &&
       secret.dig("metadata", "annotations", "reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces") == "messaging-lab",
       "Development password must be encrypted and reflection restricted")
puts "Messaging lab manifest checks passed"
