# External GitHub workflow dispatchers

These configurations use a GitHub App to dispatch a GitHub Actions workflow.
The GitLab pipeline and Cloudflare Worker are independent options. Both default
to this repository's Renovate workflow, and can be configured to dispatch
another workflow in any repository the App installation can access.

The standalone GitLab pipeline is at
`external-workflow-dispatchers/.gitlab-ci.yml`.

## GitHub App requirements

Create or use a GitHub App installed on the target repository. Grant it
**Actions: Read and write** repository permission, then generate a private key.
You will need the App ID and an installation ID that can access the target
repository.

## Dispatch target

Both dispatchers support these settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `TARGET_REPOSITORY` | `andreibe24/homelab-infrastructure` | Target in `owner/repository` format |
| `TARGET_WORKFLOW` | `renovate.yaml` | Workflow filename or numeric workflow ID |
| `TARGET_REF` | `main` | Branch or tag to run the workflow from |
| `TARGET_INPUTS_JSON` | `{}` | Optional JSON object of `workflow_dispatch` inputs |

The workflow must support the `workflow_dispatch` event. Input names and values
must match that workflow's declared `workflow_dispatch.inputs`.

## GitLab CI

If your GitLab project is separate from this GitHub repository, copy
`external-workflow-dispatchers/.gitlab-ci.yml` by itself to the GitLab project's
root and name it `.gitlab-ci.yml`. It is standalone and does not need any other
files from this repository. Files present only in GitHub are not automatically
used by GitLab. If you use this whole repository as the GitLab project instead,
set GitLab's CI/CD configuration file path to
`external-workflow-dispatchers/.gitlab-ci.yml`.

In **Settings → CI/CD → General pipelines**, use `.gitlab-ci.yml` as the
**CI/CD configuration file** in the separate-project setup (the default after
copying it to the project root).

In **Settings → CI/CD → Variables**, add:

| Key | Value |
| --- | --- |
| `GITHUB_APP_ID` | The numeric App ID from the GitHub App settings |
| `GITHUB_INSTALLATION_ID` | The numeric ID of that App's installation on the target account or organization |
| `GITHUB_APP_PRIVATE_KEY_FILE` | Full PEM private key; set **Type** to **File** |

To find `GITHUB_INSTALLATION_ID`, open the app under GitHub's **Settings →
Applications → Installed GitHub Apps**, click **Configure**, and copy the
number from the URL, for example `https://github.com/settings/installations/12345678`.
For an organization installation, open **Installed GitHub Apps** in the
organization's settings instead. This is the App installation ID, not the App
ID. Ensure that installation has access to the target repository.

GitLab cannot mask a multiline PEM value. Leave **Masked** unchecked for the
File variable; mark it **Protected** if the schedule targets a protected branch.
Protect the other credential variables as appropriate, and don't print their
values in CI logs.

Create a schedule under **Build → Pipeline schedules**, target the branch with
the config, and set the cron to `33 1-23/2 * * *`. Choose the intended timezone
in the schedule settings. The job runs only for scheduled pipelines, not normal
push pipelines. You can set `TARGET_*` variables on the schedule to override
the defaults; for example, set `TARGET_WORKFLOW` to `build.yml` and
`TARGET_INPUTS_JSON` to `{"environment":"staging"}` to pass an input.

## Cloudflare Worker

From the repository root, edit the `TARGET_*` values in
`cloudflare/wrangler.jsonc`, then deploy with Wrangler:

```sh
cd external-workflow-dispatchers/cloudflare
npx wrangler secret put GITHUB_APP_ID
npx wrangler secret put GITHUB_INSTALLATION_ID
npx wrangler secret put GITHUB_APP_PRIVATE_KEY
npx wrangler deploy
```

Enter the App ID and installation ID as the first two secret values, and paste
the full PEM private key for the third. The Worker accepts both PKCS#1 and
PKCS#8 PEM private keys. `TARGET_*` values are non-secret Wrangler vars; redeploy
after changing them.

`wrangler.jsonc` configures the Cloudflare Cron Trigger for
`43 1-23/2 * * *`. Cloudflare cron schedules use **UTC**, so this does not
track Bucharest local time through daylight-saving changes.

## Avoiding duplicate runs

The schedules are intentionally staggered: GitHub Actions at minute 13,
GitLab at minute 33, and Cloudflare at minute 43 of every other odd-numbered
hour. GitHub Actions uses Bucharest time; Cloudflare uses UTC. Each dispatcher
only starts the GitHub Actions workflow and does not run it directly.
