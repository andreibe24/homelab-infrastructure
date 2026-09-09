My Todo List:

0. Kubernetes setup with fluxcd

1. mutual TLS -> Linkerd (has communication encrypted between application pods)

        for 2 identities, mutual means that each part verifies the tls cert of the other part
2. CI with self-hosted internal Argo Workflows

        github.com code <- https outbound <- k8s cronjob poller -> new commit -> argo workflow ... 
        build (buildkit or kaniko for multi-arch, maybe somthing docker-bake style?) and push artifacts
        linting
        testing

        OR just register github runners as you need ONLY outbound connection from runner to github.com (that's because the github runner process does infinite https long-poll requests to github.com, when github.com has a job for runner it responds to the https request with the job content; secondly, github runner sends a websocket request to github.com to send in real-time the status of job ).
        A github runner needs to be registered first, the registration token is valid for 1h. If you would be able to set registration token to 1 year, the registration token would let someone keep creating new footholds indefinitely. Once, they are registered, they get .credentials.
        keep in mind that github runner .credentials (oauth runner identity) doesn't expiry; therefore, anyone that stoles this can:
                Copy the .credentials file to their own machine — nothing ties it to your VM's hardware/IP; it's pure data
                Run the runner binary there, using that stolen file — GitHub's Token Service sees the matching public key/clientId and issues a fresh OAuth token, no questions asked
                Sit in the job queue as your runner, listening via the exact same long-poll mechanism we discussed
                Receive real jobs that get dispatched to your repo/org with matching labels (self-hosted, linux, etc.) — if your actual CI triggers a deploy job, their machine might pick it up instead of (or racing) your real VM
                See everything that job exposes: the checked-out repo code, any secrets.* your workflow passes in as environment variables (API keys, deploy credentials, your PAT_TOKEN if a workflow uses it), and whatever your job's steps do — including, in your specific setup, the github user's passwordless sudo rights to run nginx -s reload and write access to /websites/my-website
                Execute arbitrary commands defined in whatever workflow file triggers next — meaning if they can also influence workflow content (e.g., via a separate compromise, or if your repo allows untrusted PR workflows onto self-hosted runners — the exact risk we discussed earlier!), they get code execution on their own machine "as your runner"
                What they CANNOT do with just this key:

                Cannot push code, open PRs, or change repo settings — this key only authenticates as a runner, not as a GitHub user/account. It carries none of your PAT's or account's permissions.
                Cannot trigger workflows on demand — they can only pick up jobs that are already being dispatched by real triggers (a push, a PR, a schedule) to labels matching this runner; they can't invent a job out of nowhere
                Cannot access other repos/orgs — scoped strictly to whatever repo/org this specific runner was registered against
                Cannot see past job history or secrets from jobs that already ran — only what's exposed in jobs it actually picks up going forward


4. CD with Fluxcd

        webapp with http/3 (quic -> udp) + website (frontend):
         -> django backend with aioquic and Hypercorn
         -> vite build with nginx frontend

5. Observability

        prometheus metrics
        grafana dashboard
        alertmanager -> notify incidents, k8s cronjob poller fails, etc. 

6. Renovate

        update packages automatically, once a day
