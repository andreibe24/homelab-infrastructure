My Todo List:

0. Kubernetes setup with fluxcd

1. mutual TLS -> Linkerd (has communication encrypted between application pods)

        for 2 identities, mutual means that each part verifies the tls cert of the other part
2. CI with self-hosted internal Argo Workflows

        github.com code <- https outbound <- k8s cronjob poller -> new commit -> argo workflow ... 
        build (buildkit or kaniko for multi-arch, maybe somthing docker-bake style?) and push artifacts
        linting
        testing

        OR just register github runners as you need ONLY outbound connection from runner to github.com (that's because the github runner process does infinite https long-poll requests to github.com, when github.com has a job for runner it responds to the https request with the job content; secondly, github runner sends a websocket request to github.com to send in real-time the status of job )



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
