# Remote storage and backups (Google Drive)

A Google Drive account provides file storage for applications and the backup
target for databases and volumes. Nothing in Git is specific to Google Drive:
workloads use the generic `s3-storage` gateway and the `backup-scripts`
component, and only the rclone configuration Secret knows the provider.

## Components

- `infrastructure/components/s3-storage/`: an rclone S3 gateway
  (`s3-storage.s3-storage.svc.cluster.local:8080`) over the Drive folder
  `apps/`. Each sub-folder is a bucket; use one bucket named after the app.
- `infrastructure/backup/component/`: a Kustomize component that generates the
  `backup-scripts` ConfigMap (dump, restore, archive, upload with retention).
  Include it from any Kustomization that has backup CronJobs
  (`components: [../../backup/component]`).
- `scripts/storage-ctl.sh`: operator CLI for setup, listing, restore and delete.

Drive layout: `apps/<app>/` for application files and
`backups/<app>/<item>/<item>-<UTC timestamp>.{dump,tar.gz}` for backups.
Files are deleted without using the Drive trash so deletions free quota.

## Setup (once)

```sh
scripts/storage-ctl.sh setup
```

It stores the rclone configuration (Drive token) as `s3-storage-backend` in
`s3-storage`, `webapp-django-vite` and `agentgateway`, and generates S3 keys in
`s3-storage-credentials`. Credentials exist only in the cluster; they are
never committed. Override `SECRET_NAMESPACES` to add namespaces. Because the
Secrets are created out of band, back up the Drive token securely and re-run
`setup` after rebuilding the cluster. Namespaces that run backup jobs need the
Secret before the first run.

For an application that needs file storage, give it the output of
`scripts/storage-ctl.sh s3-credentials` through its own SOPS-encrypted Secret
(see [secrets.md](../secrets.md)), use path-style S3 addressing, and allow its
egress to the `s3-storage` namespace if it has restrictive policies.

## What is backed up

| Data | Mechanism | Schedule | Kept |
| --- | --- | --- | --- |
| `chat-db` PostgreSQL | `pg_dump` custom format | 02:15 UTC | 14 |
| `chat-vectors` PostgreSQL | `pg_dump` custom format | 02:30 UTC | 14 |
| Agentgateway rate-limit Dragonfly (Redis) | tar of the snapshot PVC | 03:02 UTC | 3 |

Each dump is verified with `pg_restore --list` before upload. Retention on
Drive keeps only the newest `KEEP_LAST` files per item.

## Operations

```sh
scripts/storage-ctl.sh list webapp-django-vite
scripts/storage-ctl.sh backup backup-chat-db -n webapp-django-vite

# Restore the newest (or --file <name>) dump into the app database
scripts/storage-ctl.sh restore-pg webapp-django-vite chat-db -n webapp-django-vite --cluster chat-db

# Restore a volume; scale its workload down first so the PVC is not in use
scripts/storage-ctl.sh restore-pvc agentgateway agentgateway-ratelimit-dragonfly \
  -n agentgateway --claim df-agentgateway-ratelimit-dragonfly-0

# Delete everything stored for an application (files and backups)
scripts/storage-ctl.sh delete-app webapp-django-vite
```

`restore-pg` replaces existing objects (`--clean --if-exists`); stop the
application first for a consistent restore. Stop the Dragonfly workload through
its operator-managed resource before `restore-pvc`; its counters are transient
rate-limit state, so restoring them is rarely needed.

## Retention policies

- PostgreSQL (`chat-db`, `chat-vectors`): `max_wal_size`,
  `max_slot_wal_keep_size` and `temp_file_limit` cap WAL and temp-file growth.
- Dragonfly: snapshots every 5 minutes into a single overwritten file
  (`--dbfilename=dump`) instead of a new set every minute.
- Prometheus: 2 days and a 2 GB size cap.
- Drive backups: newest 14/14/3 per item as above; completed backup Jobs
  expire after 24 hours.

## Adding backups for another application

Add the component to the app's Kustomization, create a CronJob like
`apps/webapp-django-vite/webapp-django-vite.backup-cronjobs.yaml` (PostgreSQL)
or `infrastructure/components/agentgateway-ratelimit/agentgateway-ratelimit-dragonfly.cronjob.yaml`
(volume), and use a unique `APP`/`ITEM`. Mount the Secret `s3-storage-backend`.

## Google Drive notes

The token needs the full `drive` scope so jobs can manage files created by
others. Consider a dedicated Google account or the `root_folder_id` prompt to
confine access to one folder. Drive has API rate limits and upload quotas; the
free 15 GB is shared with all uses of the account.
