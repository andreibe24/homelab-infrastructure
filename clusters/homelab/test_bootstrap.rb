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
    assert_equal 2, calls.lines.count { |line| line == "apply-config\n" }
  end

  def test_flux_renders_a_separate_cilium_and_suspended_shared_roots
    entry = render("clusters/homelab/init-manifests")
    assert_equal true, entry.find { |r| r.dig("metadata", "name") == "apps" }.dig("spec", "suspend")
    assert_equal true, entry.find { |r| r.dig("metadata", "name") == "infrastructure" }.dig("spec", "suspend")
    imported = render("clusters/homelab/imported")
    cilium = imported.find { |r| r.dig("metadata", "name") == "cilium" }
    assert_equal "./clusters/homelab/imported/cilium", cilium.dig("spec", "path")
    assert_equal "homelab-cilium-settings", cilium.dig("spec", "postBuild", "substituteFrom", 0, "name")
    resources = render("clusters/homelab/imported/cilium")
    values = resources.find { |r| r["kind"] == "ConfigMap" }.dig("data", "values.yaml")
    assert_includes values, "k8sServiceHost: ${HOMELAB_API_HOST}"
    assert_includes values, "hostRoot: /sys/fs/cgroup"
    refute_includes values, "dev-control-plane"
  end

  def render(path)
    output, status = Open3.capture2e("kubectl", "kustomize", path, chdir: ROOT)
    assert status.success?, output
    YAML.safe_load_stream(output)
  end
end
