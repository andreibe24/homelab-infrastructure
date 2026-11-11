require "open3"
require "openssl"
require "yaml"

ROOT = File.expand_path("../../..", __dir__)

def build(path)
  command = ENV["KUSTOMIZE"] ? [ENV["KUSTOMIZE"], "build", path] : ["kubectl", "kustomize", path]
  output, status = Open3.capture2e(*command, chdir: ROOT)
  abort output unless status.success?
  YAML.load_stream(output).compact
end

def resource(resources, kind, name)
  resources.find { |item| item["kind"] == kind && item.dig("metadata", "name") == name } ||
    abort("Missing #{kind}/#{name}")
end

def assert(condition, message)
  abort message unless condition
end

registration = build("clusters/dev/identity/registration")
identity = build("clusters/dev/identity/keycloak")
trust = build("clusters/dev/identity/trust")
secrets = build("clusters/dev/init-manifests/secrets")
apps = build("apps/webapp-django-vite")
monitoring = build("infrastructure/components/monitoring")

operator = resource(registration, "Kustomization", "keycloak-operator")
assert(operator.dig("spec", "prune") == false, "Operator CRDs must not be pruned")
assert(resource(registration, "Namespace", "keycloak").dig("metadata", "annotations",
  "kustomize.toolkit.fluxcd.io/prune") == "disabled", "Identity namespace must not be pruned")

server = resource(identity, "Keycloak", "keycloak")
realm = resource(identity, "KeycloakRealmImport", "homelab")
assert(server.dig("spec", "hostname", "hostname") == "https://identity.localhost:8443",
  "Wrong public Keycloak hostname")
assert(server.dig("spec", "http", "tlsSecret") == "keycloak-backchannel-tls",
  "Backchannel TLS must remain enabled")
assert(server.dig("spec", "networkPolicy", "http").map { |peer| peer.dig("namespaceSelector", "matchLabels", "kubernetes.io/metadata.name") } == ["gateway"],
  "Forwarded HTTP must be restricted to the gateway")
clients = realm.dig("spec", "realm", "clients").to_h { |client| [client["clientId"], client] }
assert(clients.keys.sort == %w[campfire grafana], "Unexpected OIDC clients")
assert(clients["campfire"]["redirectUris"] == ["https://campfire.localhost:8443/api/oidc/callback/"],
  "Wrong Campfire callback")
assert(clients["grafana"]["redirectUris"] == ["https://grafana.localhost:8443/login/generic_oauth"],
  "Wrong Grafana callback")
assert(clients.values.all? { |client| client["publicClient"] == false && client["directAccessGrantsEnabled"] == false },
  "OIDC clients must be confidential and disallow password grants")

bundles = trust.select { |item| item["kind"] == "ConfigMap" && item.dig("metadata", "name") == "identity-ca" }
assert(bundles.map { |item| item.dig("metadata", "namespace") }.sort == %w[monitoring webapp-django-vite],
  "Identity CA must be available to both clients")
assert(bundles.map { |item| item.dig("data", "ca.crt") }.uniq.size == 1, "CA bundles differ")
certificate = OpenSSL::X509::Certificate.new(bundles.first.dig("data", "ca.crt"))
assert(certificate.verify(certificate.public_key) && certificate.not_after > Time.now, "Invalid identity CA")

values = YAML.safe_load(resource(trust, "ConfigMap", "grafana-oidc-values").dig("data", "values.yaml"))
oauth = values.dig("grafana", "grafana.ini", "auth.generic_oauth")
assert(oauth["validate_id_token"] && oauth["tls_client_ca"] == "/etc/identity-ca/ca.crt",
  "Grafana must validate ID tokens and backchannel TLS")
assert(values.dig("grafana", "env", "SSL_CERT_FILE") == "/etc/identity-ca/ca.crt",
  "Grafana's JWKS client must trust the backchannel CA")
assert(oauth["auth_url"].start_with?("https://identity.localhost:8443/realms/homelab/") &&
  oauth["token_url"].start_with?("https://keycloak-service.keycloak.svc.cluster.local:8443/"),
  "Grafana issuer/backchannel mismatch")
release = resource(monitoring, "HelmRelease", "monitoring")
assert(release.dig("spec", "valuesFrom").any? { |entry| entry["name"] == "grafana-oidc-values" && entry["optional"] },
  "Grafana values must be optional outside dev")
deployment = resource(apps, "Deployment", "webapp-django-vite-backend")
assert(deployment.dig("spec", "template", "spec", "containers", 0, "envFrom").any? { |entry|
  entry.dig("secretRef", "name") == "campfire-oidc" && entry.dig("secretRef", "optional")
}, "Campfire OIDC must be opt-in outside dev")

%w[identity-ca campfire-oidc grafana-oidc].each do |name|
  secret = resource(secrets, "Secret", name)
  assert(secret.fetch("stringData").values.all? { |value| value.start_with?("ENC[AES256_GCM,") },
    "#{name} contains unencrypted values")
  assert(secret.dig("sops", "encrypted_regex") == "^(data|stringData)$", "#{name} is not SOPS-protected")
end

puts "Dev identity manifest checks passed"
