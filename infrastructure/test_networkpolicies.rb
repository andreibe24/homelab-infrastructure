#!/usr/bin/env ruby
require "open3"
require "yaml"

root = File.expand_path("..", __dir__)
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

apps = build(root, "apps", kustomize)
components = build(root, "infrastructure/components", kustomize)
imported = build(root, "infrastructure/imported/cilium", kustomize)
ratelimit = build(root, "infrastructure/components/agentgateway-ratelimit", kustomize)
policies = (apps + components + imported + ratelimit).select { |resource| resource["kind"] == "NetworkPolicy" }
namespaces = (apps + components).select { |resource| resource["kind"] == "Namespace" }
app_names = apps.select { |resource| resource["kind"] == "Namespace" }.map { |resource| resource.dig("metadata", "name") }
component_names = components.select { |resource| resource["kind"] == "Namespace" }.map { |resource| resource.dig("metadata", "name") }

assert(!app_names.empty? && !component_names.empty?, "Missing application or infrastructure namespaces")
assert(namespaces.size == (app_names + component_names).uniq.size, "Duplicate namespaces")

app_names.each do |namespace|
  policy = policies.find { |item| item.dig("metadata", "namespace") == namespace && item.dig("metadata", "name") == "application-ingress" }
  assert(policy && policy.dig("spec", "podSelector") == {} && policy.dig("spec", "policyTypes") == ["Ingress"],
         "Missing ingress isolation for #{namespace}")
  peers = policy.dig("spec", "ingress").flat_map { |rule| rule.fetch("from", []) }
  allowed_names = peers.filter_map { |peer| peer.dig("namespaceSelector", "matchLabels", "kubernetes.io/metadata.name") }
  expected = %w[gateway monitoring]
  expected << "postgres-operator" if namespace == "webapp-django-vite"
  assert(peers.include?({ "podSelector" => {} }) && allowed_names.sort == expected.sort && peers.size == expected.size + 1,
         "Unexpected ingress peers for #{namespace}")
end

(component_names + ["kube-system"]).each do |namespace|
  policy = policies.find { |item| item.dig("metadata", "namespace") == namespace && item.dig("metadata", "name") == "cluster-ingress" }
  assert(policy && policy.dig("spec", "policyTypes") == ["Ingress"] &&
         policy.dig("spec", "ingress") == [{ "from" => [{ "namespaceSelector" => {} }] }],
         "Missing cluster ingress isolation for #{namespace}")
  selector = policy.dig("spec", "podSelector")
  if namespace == "agentgateway"
    assert(selector == { "matchExpressions" => [{ "key" => "app", "operator" => "NotIn",
                                                   "values" => %w[agentgateway-ratelimit agentgateway-ratelimit-dragonfly] }] },
           "Cluster policy must not widen rate-limiter ingress")
  else
    assert(selector == {}, "Cluster policy must select all pods in #{namespace}")
  end
end

flux_instance = YAML.load_file(File.join(root, "clusters/dev/bootstrap/flux.fluxinstance.yaml"))
assert(flux_instance.dig("spec", "cluster", "networkPolicy") == true,
       "Flux must continue to generate its own network policies")
flux_operator = build(root, "infrastructure/imported/flux-operator", kustomize)
assert(flux_operator.none? { |resource| resource["kind"] == "NetworkPolicy" },
       "An additional Flux policy could widen the generated policies")

%w[agentgateway-ratelimit agentgateway-ratelimit-dragonfly].each do |name|
  policy = policies.find { |item| item.dig("metadata", "namespace") == "agentgateway" && item.dig("metadata", "name") == name }
  assert(policy && policy.dig("spec", "podSelector", "matchLabels", "app") == name &&
         policy.dig("spec", "policyTypes").sort == %w[Egress Ingress],
         "Missing restrictive policy for #{name}")
end

puts "Network policy coverage checks passed"
