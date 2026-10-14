# Instructions

## Flux

```bash
flux-operator create secret basic-auth git-creds \
  --namespace=flux-system --username=<user> --password=<token>

flux-operator install -f flux-instance.yaml
```
