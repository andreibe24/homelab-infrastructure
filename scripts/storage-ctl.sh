#!/usr/bin/env bash
# Operate the remote-storage (Google Drive) integration: set up credentials,
# list/run/restore backups and delete all files stored for an application.
# Credentials live only in cluster Secrets, never in Git. See docs/components/s3-storage.md.
set -euo pipefail

RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:1.75.2}"
PG_IMAGE="${PG_IMAGE:-ghcr.io/cloudnative-pg/postgresql:17.6}"
# Namespaces that need the backend Secret: the gateway, backup jobs and apps.
SECRET_NAMESPACES="${SECRET_NAMESPACES:-s3-storage webapp-django-vite agentgateway}"
BACKEND_SECRET=s3-storage-backend
CREDENTIALS_SECRET=s3-storage-credentials

usage() {
  cat <<'EOF'
Usage: scripts/storage-ctl.sh <command> [args]

  setup                        Create the Secrets (prompts for a Google Drive token)
  list <app> [item]            List backups of an app (all items, or one)
  backup <cronjob> -n <ns>     Run a backup CronJob now
  restore-pg <app> <item> -n <ns> --cluster <cnpg-cluster> [--file <name>]
                               Restore a PostgreSQL dump (default: latest) into the
                               app database of the CNPG cluster's read-write service
  restore-pvc <app> <item> -n <ns> --claim <pvc> [--file <name>]
                               Replace PVC contents with a backup; the PVC must not
                               be in use (scale the workload down first)
  delete-app <app> [--yes]     Delete ALL stored files and backups of an app
  s3-credentials               Print the S3 endpoint and keys for applications

Environment: SECRET_NAMESPACES, RCLONE_IMAGE, PG_IMAGE.
EOF
  exit 1
}

die() { echo "error: $*" >&2; exit 1; }

# Run a one-off Job and stream its logs. Args: namespace name; Job spec on stdin.
run_job() {
  local ns=$1 name=$2
  kubectl -n "$ns" delete job "$name" --ignore-not-found >/dev/null
  kubectl -n "$ns" apply -f - >/dev/null
  kubectl -n "$ns" wait --for=condition=ready pod -l "job-name=$name" --timeout=120s >/dev/null 2>&1 || true
  kubectl -n "$ns" logs -f "job/$name" --all-containers --prefix 2>/dev/null || true
  if kubectl -n "$ns" wait --for=condition=complete "job/$name" --timeout=3600s >/dev/null 2>&1; then
    kubectl -n "$ns" delete job "$name" >/dev/null
  else
    echo "job $ns/$name failed; inspect with: kubectl -n $ns describe job $name" >&2
    exit 1
  fi
}

# Common pod fragments: rclone download container shared by the restore jobs.
rclone_env() { # app item file
  cat <<EOF
                - {name: APP, value: "$1"}
                - {name: ITEM, value: "$2"}
                - {name: FILE, value: "${3:-latest}"}
EOF
}

parse_opts() {
  NS="" CLUSTER="" CLAIM="" FILE="" YES=""
  while [ $# -gt 0 ]; do
    case $1 in
      -n) NS=$2; shift 2 ;;
      --cluster) CLUSTER=$2; shift 2 ;;
      --claim) CLAIM=$2; shift 2 ;;
      --file) FILE=$2; shift 2 ;;
      --yes) YES=1; shift ;;
      *) die "unknown option $1" ;;
    esac
  done
}

cmd_setup() {
  command -v rclone >/dev/null || die "rclone is required locally to authorize Google Drive"
  echo "Authorize Google Drive. Run 'rclone authorize \"drive\" --drive-scope drive.file' on a machine"
  echo "with a browser if this one has none, then paste the token JSON below."
  read -r -s -p "Token JSON (hidden; leave empty to run rclone authorize here): " token; echo
  if [ -z "$token" ]; then
    token=$(rclone authorize drive --drive-scope drive.file | awk '/^\{.*\}$/ {print}')
  fi
  [ -n "$token" ] || die "no token provided"
  read -r -p "Optional Drive root folder ID to confine access (empty = whole drive): " root
  local conf
  conf=$(printf '[storage]\ntype = drive\nscope = drive\ntoken = %s\nroot_folder_id = %s\n' "$token" "$root")
  local access secret
  access=$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)
  secret=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)
  for ns in $SECRET_NAMESPACES; do
    kubectl get ns "$ns" >/dev/null 2>&1 || kubectl create ns "$ns" >/dev/null
    kubectl -n "$ns" create secret generic "$BACKEND_SECRET" \
      --from-literal=rclone.conf="$conf" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  done
  kubectl -n s3-storage create secret generic "$CREDENTIALS_SECRET" \
    --from-literal=access-key="$access" --from-literal=secret-key="$secret" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  echo "Secrets created in: $SECRET_NAMESPACES. Show app credentials with: $0 s3-credentials"
  echo "Note: scope 'drive' is needed so jobs can manage files created by other jobs."
}

cmd_s3_credentials() {
  echo "endpoint:   http://s3-storage.s3-storage.svc.cluster.local:8080"
  echo "bucket:     <app name> (created on first use; one bucket per app)"
  echo "access key: $(kubectl -n s3-storage get secret $CREDENTIALS_SECRET -o jsonpath='{.data.access-key}' | base64 -d)"
  echo "secret key: $(kubectl -n s3-storage get secret $CREDENTIALS_SECRET -o jsonpath='{.data.secret-key}' | base64 -d)"
  echo "region:     any (path-style addressing required)"
}

# Run rclone inside the cluster using the stored backend Secret.
cmd_rclone() { # args passed to rclone
  local args=""
  for a in "$@"; do args="$args \"$a\""; done
  local ns=s3-storage
  run_job "$ns" storage-ctl-rclone <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: storage-ctl-rclone}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true, runAsUser: 65532, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: rclone
          image: $RCLONE_IMAGE
          command: ["/bin/sh", "-c"]
          args:
            - cp /storage-config/rclone.conf /tmp/rclone.conf && exec rclone --config /tmp/rclone.conf --drive-use-trash=false $args
          env: [{name: HOME, value: /tmp}]
          volumeMounts:
            - {name: storage-config, mountPath: /storage-config, readOnly: true}
            - {name: tmp, mountPath: /tmp}
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumes:
        - {name: storage-config, secret: {secretName: $BACKEND_SECRET}}
        - {name: tmp, emptyDir: {}}
EOF
}

cmd_list() {
  [ $# -ge 1 ] || usage
  cmd_rclone lsl "storage:backups/$1${2:+/$2}" --max-depth 2 -R
}

cmd_backup() {
  [ $# -ge 1 ] || usage
  local cj=$1; shift; parse_opts "$@"; [ -n "$NS" ] || die "-n <namespace> required"
  local job="${cj}-manual-$(date +%s)"
  kubectl -n "$NS" create job --from="cronjob/$cj" "$job"
  kubectl -n "$NS" wait --for=condition=complete "job/$job" --timeout=1800s
  kubectl -n "$NS" logs "job/$job" --all-containers --prefix
}

# Restore jobs: an initContainer downloads the backup, a second container applies it.
restore_job() { # ns name app item file image apply-script extra-env volume-yaml mount-yaml
  local ns=$1 name=$2 app=$3 item=$4 file=$5 image=$6 script=$7 extra_env=$8 vols=$9 mounts=${10}
  run_job "$ns" "$name" <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: $name}
spec:
  backoffLimit: 0
  template:
    metadata: {labels: {homelab.local/backup: "true"}}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext: {runAsNonRoot: true, runAsUser: 26, runAsGroup: 26, fsGroup: 26, seccompProfile: {type: RuntimeDefault}}
      initContainers:
        - name: download
          image: $RCLONE_IMAGE
          command: ["/bin/sh", "/scripts/download.sh"]
          env:
$(rclone_env "$app" "$item" "$file")
          volumeMounts:
            - {name: work, mountPath: /work}
            - {name: scripts, mountPath: /scripts}
            - {name: storage-config, mountPath: /storage-config, readOnly: true}
            - {name: tmp, mountPath: /tmp}
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      containers:
        - name: restore
          image: $image
          command: ["/bin/sh", "/scripts/$script"]
          env:
$extra_env
          volumeMounts:
            - {name: work, mountPath: /work}
            - {name: scripts, mountPath: /scripts}
$mounts
          securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumes:
        - {name: work, emptyDir: {sizeLimit: 8Gi}}
        - {name: tmp, emptyDir: {sizeLimit: 64Mi}}
        - {name: scripts, configMap: {name: backup-scripts, defaultMode: 0555}}
        - {name: storage-config, secret: {secretName: $BACKEND_SECRET}}
$vols
EOF
}

cmd_restore_pg() {
  [ $# -ge 2 ] || usage
  local app=$1 item=$2; shift 2; parse_opts "$@"
  [ -n "$NS" ] && [ -n "$CLUSTER" ] || die "-n and --cluster are required"
  read -r -p "Overwrite database objects in cluster $NS/$CLUSTER from backup '${FILE:-latest}'? [y/N] " ok
  [ "$ok" = y ] || die "aborted"
  local env
  env=$(cat <<EOF
            - {name: PGHOST, value: ${CLUSTER}-rw}
            - {name: PGDATABASE, valueFrom: {secretKeyRef: {name: ${CLUSTER}-app, key: dbname}}}
            - {name: PGUSER, valueFrom: {secretKeyRef: {name: ${CLUSTER}-app, key: username}}}
            - {name: PGPASSWORD, valueFrom: {secretKeyRef: {name: ${CLUSTER}-app, key: password}}}
EOF
)
  restore_job "$NS" "restore-$CLUSTER" "$app" "$item" "$FILE" "$PG_IMAGE" pg-restore.sh "$env" "" ""
}

cmd_restore_pvc() {
  [ $# -ge 2 ] || usage
  local app=$1 item=$2; shift 2; parse_opts "$@"
  [ -n "$NS" ] && [ -n "$CLAIM" ] || die "-n and --claim are required"
  read -r -p "Replace ALL contents of PVC $NS/$CLAIM from backup '${FILE:-latest}'? [y/N] " ok
  [ "$ok" = y ] || die "aborted"
  local env='            - {name: DEST_DIR, value: /restore}'
  restore_job "$NS" "restore-$CLAIM" "$app" "$item" "$FILE" "$RCLONE_IMAGE" pvc-restore.sh "$env" \
    "        - {name: target, persistentVolumeClaim: {claimName: $CLAIM}}" \
    "            - {name: target, mountPath: /restore}"
}

cmd_delete_app() {
  [ $# -ge 1 ] || usage
  local app=$1; shift; parse_opts "$@"
  [[ $app =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "invalid app name"
  if [ -z "$YES" ]; then
    read -r -p "Permanently delete ALL files and backups of '$app' from remote storage? Type the app name to confirm: " ok
    [ "$ok" = "$app" ] || die "aborted"
  fi
  # purge ignores missing directories poorly, so tolerate absence of either location.
  cmd_rclone purge "storage:apps/$app" || true
  cmd_rclone purge "storage:backups/$app" || true
  echo "deleted storage:apps/$app and storage:backups/$app (Drive trash bypassed)"
}

[ $# -ge 1 ] || usage
cmd=$1; shift
case $cmd in
  setup) cmd_setup "$@" ;;
  s3-credentials) cmd_s3_credentials ;;
  list) cmd_list "$@" ;;
  backup) cmd_backup "$@" ;;
  restore-pg) cmd_restore_pg "$@" ;;
  restore-pvc) cmd_restore_pvc "$@" ;;
  delete-app) cmd_delete_app "$@" ;;
  *) usage ;;
esac
