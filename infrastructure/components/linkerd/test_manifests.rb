#!/usr/bin/env ruby
require "open3"
require "yaml"

root = File.expand_path("../../..", __dir__)
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

components = build(root, "infrastructure/components", kustomize)
apps = build(root, "apps", kustomize)
mesh = build(root, "infrastructure/components/linkerd", kustomize)
certificates = build(root, "infrastructure/components/linkerd/certificates", kustomize)
ratelimit = build(root, "infrastructure/components/agentgateway-ratelimit", kustomize)

namespaces = (components + apps).select { |resource| resource["kind"] == "Namespace" }
namespaces.each do |namespace|
  name = namespace.dig("metadata", "name")
  injection = namespace.dig("metadata", "annotations", "linkerd.io/inject")
  expected = %w[cert-manager linkerd keda metrics-server].include?(name) ? nil : "enabled"
  assert(injection == expected, "Unexpected injection setting for namespace #{name}")
end
assert(namespaces.size >= 5, "Namespace coverage is incomplete")

releases = mesh.select { |resource| resource["kind"] == "HelmRelease" }
crds = releases.find { |resource| resource.dig("metadata", "name") == "linkerd-crds" }
control_plane = releases.find { |resource| resource.dig("metadata", "name") == "linkerd-control-plane" }
assert(crds && control_plane, "Missing Linkerd Helm releases")
assert(crds.dig("spec", "chart", "spec", "version") == control_plane.dig("spec", "chart", "spec", "version"),
       "Linkerd chart versions differ")
assert(control_plane.dig("spec", "dependsOn").any? { |dependency| dependency["name"] == "linkerd-crds" },
       "Control plane must wait for CRDs")
assert(control_plane.dig("spec", "values", "identity", "issuer", "scheme") == "kubernetes.io/tls",
       "Control plane must use the cert-manager issuer")
assert(control_plane.dig("spec", "values", "proxy", "nativeSidecar") == true,
       "Jobs require native sidecars")
assert(control_plane.dig("spec", "values", "proxy", "outboundTransportMode") == "transparent",
       "Transport headers would bypass network-policy port restrictions")
assert(control_plane.dig("spec", "valuesFrom").any? { |value|
  value["name"] == "linkerd-trust-anchor" && value["valuesKey"] == "tls.crt" &&
    value["targetPath"] == "identityTrustAnchorsPEM"
}, "Control plane must use the generated trust anchor")

flux = components.select { |resource| resource["apiVersion"] == "kustomize.toolkit.fluxcd.io/v1" }
flux_by_name = flux.to_h { |resource| [[resource.dig("metadata", "namespace"), resource.dig("metadata", "name")], resource] }
depends_on_mesh = lambda do |key, seen|
  return true if key == ["linkerd", "linkerd"]
  return false if seen.include?(key) || !flux_by_name.key?(key)

  resource = flux_by_name.fetch(key)
  resource.dig("spec", "dependsOn").to_a.any? do |dependency|
    depends_on_mesh.call([dependency["namespace"] || key[0], dependency["name"]], seen + [key])
  end
end
%w[envoy-gateway/envoy-gateway gateway/gateway reflector/reflector reloader/reloader
   postgres-operator/cloudnative-pg redis-operator/dragonfly-operator falco/falco
   monitoring/monitoring agentgateway/agentgateway agentgateway/agentgateway-ratelimit
   agentgateway/agentgateway-config].each do |entry|
  assert(depends_on_mesh.call(entry.split("/"), []), "#{entry} must wait for Linkerd")
end
mesh_flux = flux_by_name.fetch(["linkerd", "linkerd"])
assert(mesh_flux.dig("spec", "dependsOn").any? { |dependency| dependency["name"] == "linkerd-certificates" },
       "Linkerd must wait for certificates")

issuer = certificates.find { |resource| resource.dig("metadata", "name") == "linkerd-identity-issuer" }
assert(issuer.dig("spec", "isCA") && issuer.dig("spec", "privateKey", "algorithm") == "ECDSA" &&
       issuer.dig("spec", "privateKey", "rotationPolicy") == "Always",
       "Identity issuer must be a rotating ECDSA CA")

policies = ratelimit.select { |resource| resource["kind"] == "NetworkPolicy" }
dragonfly = ratelimit.find { |resource| resource["kind"] == "Dragonfly" }
assert(dragonfly.dig("spec", "podMetadata", "labels", "app") == "agentgateway-ratelimit-dragonfly",
       "Dragonfly pods must match their network policies")
assert(dragonfly.dig("spec", "podMetadata", "annotations", "config.linkerd.io/opaque-ports") == "" &&
       dragonfly.dig("spec", "serviceSpec", "annotations", "config.linkerd.io/opaque-ports") == "",
       "Dragonfly Redis traffic must not use the shared opaque transport port")
%w[agentgateway-ratelimit agentgateway-ratelimit-dragonfly].each do |name|
  policy = policies.find { |resource| resource.dig("metadata", "name") == name }
  assert(policy, "Missing network policy #{name}")
  ports = policy.dig("spec", "egress").flat_map { |rule| rule.fetch("ports", []).map { |port| port["port"] } }
  assert(([53, 8080, 8086, 8090] - ports).empty?, "Missing Linkerd egress in #{name}")
  all_ports = (policy.dig("spec", "ingress") + policy.dig("spec", "egress")).flat_map do |rule|
    rule.fetch("ports", []).map { |port| port["port"] }
  end
  assert(!all_ports.include?(4143), "Shared proxy port must not bypass application-port policies in #{name}")
end

puts "Linkerd manifest checks passed"
