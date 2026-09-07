My Todo List:

0. Kubernetes setup with fluxcd

1. mutual TLS -> Linkerd (has communication encrypted between application pods)

        for 2 identities, mutual means that each part verifies the tls cert of the other part
2. CI with self-hosted internal Argo Workflows

        github.com code <- https outbound <- k8s cronjob poller -> new commit -> argo workflow ... 
        build (buildkit or kaniko for multi-arch, maybe somthing docker-bake style?) and push artifacts
        linting
        testing



4. CD with Fluxcd

        webapp with http/3 (quic -> udp) + website (frontend):
         -> django backend with aioquic and Hypercorn
         -> vite build with nginx frontend
