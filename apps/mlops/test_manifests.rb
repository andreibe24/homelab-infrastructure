#!/usr/bin/env ruby
require "open3"
require "yaml"

root = File.expand_path("../..", __dir__)
command = ENV["KUSTOMIZE"] ? [ENV["KUSTOMIZE"], "build", "apps/mlops"] : ["kubectl", "kustomize", "apps/mlops"]
output, status = Open3.capture2e(*command, chdir: root)
abort output unless status.success?
resources = YAML.load_stream(output).compact

def resource(resources, kind, name)
  resources.find { |item| item["kind"] == kind && item.dig("metadata", "name") == name } ||
    abort("Missing #{kind} #{name}")
end

job = resource(resources, "Job", "mlops-training-initial")
cron = resource(resources, "CronJob", "mlops-training")
abort "Training job templates differ" unless job.dig("spec", "template") == cron.dig("spec", "jobTemplate", "spec", "template")
abort "Training job limits differ" unless %w[backoffLimit activeDeadlineSeconds].all? do |key|
  job.dig("spec", key) == cron.dig("spec", "jobTemplate", "spec", key)
end
abort "Concurrent training jobs are allowed" unless cron.dig("spec", "concurrencyPolicy") == "Forbid"
deployment = resource(resources, "Deployment", "mlflow")
abort "MLflow must use a single persistent writer" unless deployment.dig("spec", "replicas") == 1 &&
  deployment.dig("spec", "strategy", "type") == "Recreate" &&
  deployment.dig("spec", "template", "spec", "volumes").any? { |volume| volume.dig("persistentVolumeClaim", "claimName") == "mlflow-data" }
args = deployment.dig("spec", "template", "spec", "containers", 0, "command")
hosts = args.fetch(args.index("--allowed-hosts") + 1).split(",")
abort "MLflow must allow the client and port-forward Host headers" unless %w[mlflow:5000 localhost:5000 127.0.0.1:5000].all? { |host| hosts.include?(host) }
resource(resources, "PersistentVolumeClaim", "mlflow-data")
resource(resources, "ConfigMap", "mlops-training")
abort "MLflow must not have a public route" if resources.any? { |item| %w[Ingress HTTPRoute].include?(item["kind"]) }
puts "MLOps manifest checks passed"
