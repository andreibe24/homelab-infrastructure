require "minitest/autorun"
require "open3"
require "tmpdir"
require "fileutils"
require "yaml"

ROOT = File.expand_path("../..", __dir__)
SCRIPT = File.join(__dir__, "bootstrap/bootstrap.sh")

class HomelabBootstrapTest < Minitest::Test
  def setup
    @tmp = Dir.mktmpdir("homelab-bootstrap-test")
    @bin = File.join(@tmp, "bin")
    FileUtils.mkdir_p(@bin)
    @env = {
      "PATH" => "#{@bin}:#{ENV.fetch("PATH")}",
      "STATE_DIR" => File.join(@tmp, "state"),
      "CONTROL_PLANE_IP" => "192.0.2.10",
      "WORKER_IP" => "192.0.2.11",
      "CONTROL_PLANE_DISK" => "/dev/sda",
      "WORKER_DISK" => "/dev/nvme0n1",
      "MOCK_TALOS_VERSION" => File.read(SCRIPT).match(/^TALOS_VERSION="([^"]+)"/)[1],
      "MOCK_LOG" => File.join(@tmp, "calls")
    }
    stub("talosctl", <<~'SH')
      if [[ "${1:-}" == version ]]; then
        printf 'Client:\nTalos %s\n' "$MOCK_TALOS_VERSION"
      elif [[ "${1:-} ${2:-}" == "gen config" ]]; then
        while [[ $# -gt 0 ]]; do
          if [[ "$1" == --output ]]; then
            shift
            touch "$1/controlplane.yaml" "$1/worker.yaml" "$1/talosconfig"
            break
          fi
          shift
        done
      elif [[ " $* " == *" kubeconfig "* ]]; then
        touch "${@: -1}"
      fi
    SH
    stub("kubectl", <<~'SH')
      printf 'KUBECONFIG=%s\n' "${KUBECONFIG:-unset}" >> "$MOCK_LOG"
      if [[ " $* " == *" -f - "* ]]; then cat >/dev/null; fi
      printf 'mock\n'
    SH
    stub("helm", ":")
  end

  def teardown
    FileUtils.remove_entry(@tmp)
  end

  def stub(name, body)
    path = File.join(@bin, name)
    File.write(path, "#!/usr/bin/env bash\nprintf '%s\\n' '#{name}' \"$@\" >> \"$MOCK_LOG\"\n#{body}\n")
    File.chmod(0o755, path)
  end

  def run_step(step, extra = {})
    Open3.capture3(@env.merge(extra), "bash", SCRIPT, step, chdir: ROOT)
  end

  def test_provisioning_is_guarded_and_uses_dedicated_kubeconfig
    _, err, status = run_step("generate", "CONTROL_PLANE_IP" => "999.1.1.1")
    refute status.success?
    assert_includes err, "IPv4"
    _, err, status = run_step("generate")
    assert status.success?, err
    _, err, status = run_step("generate")
    refute status.success?
    assert_includes err, "already exists"
    _, err, status = run_step("apply")
    refute status.success?
    assert_includes err, "CONFIRM_INSTALL"
    _, err, status = run_step("apply", "CONFIRM_INSTALL" => "yes", "WORKER_IP" => "192.0.2.12")
    refute status.success?
    assert_includes err, "differs"
    _, err, status = run_step("apply", "CONFIRM_INSTALL" => "yes")
    assert status.success?, err
    _, err, status = run_step("bootstrap")
    assert status.success?, err
    _, err, status = run_step("bootstrap")
    refute status.success?
    assert_includes err, "already attempted"
    _, err, status = run_step("install")
    assert status.success?, err
    calls = File.read(@env.fetch("MOCK_LOG"))
    assert_includes calls, 'disk.dev_path == \"/dev/nvme0n1\"'
    assert_includes calls, "HOMELAB_API_HOST=192.0.2.10"
    assert_includes calls, "k8sServiceHost=192.0.2.10"
    assert_includes calls, "KUBECONFIG=#{@env.fetch("STATE_DIR")}/kubeconfig"
    assert_operator calls.index("../../../infrastructure/imported/cilium/custom.helmvalues.yaml"), :<,
                    calls.index("../../../infrastructure/imported/cilium/custom-values/homelab.yaml")
    assert_equal 2, calls.lines.count { |line| line == "apply-config\n" }
  end

  def test_flux_renders_a_separate_cilium_and_suspended_shared_roots
    entry = render("clusters/homelab/init-manifests")
    assert_equal true, entry.find { |r| r.dig("metadata", "name") == "apps" }.dig("spec", "suspend")
    assert_equal true, entry.find { |r| r.dig("metadata", "name") == "infrastructure" }.dig("spec", "suspend")
    imported = render("clusters/homelab/imported")
    cilium = imported.find { |r| r.dig("metadata", "name") == "cilium" }
    assert_equal "./infrastructure/imported/overlays/cilium/homelab", cilium.dig("spec", "path")
    assert_equal "homelab-cilium-settings", cilium.dig("spec", "postBuild", "substituteFrom", 0, "name")
    dev_imported = render("clusters/dev/imported")
    dev_entry = render("clusters/dev/init-manifests")
    imported_root = dev_entry.find { |r| r.dig("metadata", "name") == "infrastructure-imported" }
    assert_equal "./clusters/dev/imported", imported_root.dig("spec", "path")
    dev_cilium = dev_imported.find { |r| r.dig("metadata", "name") == "cilium" }
    assert_equal "./infrastructure/imported/overlays/cilium/dev", dev_cilium.dig("spec", "path")

    dev_values = cilium_values("dev")
    homelab_values = cilium_values("homelab")
    assert_equal({
      "kubeProxyReplacement" => true,
      "socketLB" => { "hostNamespaceOnly" => true },
      "k8sServiceHost" => "dev-control-plane",
      "k8sServicePort" => 6443,
      "ipam" => { "mode" => "kubernetes" },
      "operator" => { "replicas" => 1 },
      "gatewayAPI" => { "enabled" => false }
    }, dev_values)
    assert_equal "${HOMELAB_API_HOST}", homelab_values.delete("k8sServiceHost")
    assert_equal "/sys/fs/cgroup", homelab_values.dig("cgroup", "hostRoot")
    assert_equal false, homelab_values.dig("cgroup", "autoMount", "enabled")
    refute_includes homelab_values.dig("securityContext", "capabilities", "ciliumAgent"), "SYS_MODULE"
    homelab_values.delete("cgroup")
    homelab_values.delete("securityContext")
    assert_equal dev_values.reject { |key, _| key == "k8sServiceHost" }, homelab_values
  end

  def test_dev_bootstrap_uses_common_and_cluster_values
    stub("kind", ":")
    stub("docker", ":")
    home = File.join(@tmp, "home")
    key = File.join(home, ".config/sops/age/keys.txt")
    FileUtils.mkdir_p(File.dirname(key))
    File.write(key, "test key")
    _, err, status = Open3.capture3(@env.merge("HOME" => home), "bash",
                                   File.join(ROOT, "clusters/dev/bootstrap/bootstrap.sh"), chdir: ROOT)
    assert status.success?, err
    calls = File.read(@env.fetch("MOCK_LOG"))
    assert_includes calls, "../../../infrastructure/imported/cilium/custom.helmvalues.yaml"
    assert_includes calls, "../../../infrastructure/imported/cilium/custom-values/dev.yaml"
    assert_operator calls.index("../../../infrastructure/imported/cilium/custom.helmvalues.yaml"), :<,
                    calls.index("../../../infrastructure/imported/cilium/custom-values/dev.yaml")
  end

  def cilium_values(cluster)
    resources = render("infrastructure/imported/overlays/cilium/#{cluster}")
    release = resources.find { |r| r["kind"] == "HelmRelease" }
    refs = release.dig("spec", "valuesFrom")
    names = refs.map { |ref| ref.fetch("name") }
    assert_equal %w[cilium-custom-helmvalues cilium-cluster-helmvalues], names
    assert_equal "#{cluster}.yaml", refs.last.fetch("valuesKey")
    values = refs.map do |ref|
      config = resources.find { |r| r["kind"] == "ConfigMap" && r.dig("metadata", "name") == ref.fetch("name") }
      assert_equal "disabled", config.dig("metadata", "annotations", "kustomize.toolkit.fluxcd.io/prune")
      YAML.safe_load(config.dig("data", ref.fetch("valuesKey", "values.yaml")))
    end
    values.reduce({}) { |merged, value| merged.merge(value) }
  end

  def render(path)
    output, status = Open3.capture2e("kubectl", "kustomize", path, chdir: ROOT)
    assert status.success?, output
    YAML.load_stream(output).compact
  end
end
