# Instructions

## Kind
```bash
kind create cluster --name dev --config kind.yaml --kubeconfig ~/.kube/configs/dev-cluster.yaml

GW_VER=<latest release from github.com/kubernetes-sigs/gateway-api/releases>
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/${GW_VER}/standard-install.yaml

helm repo add cilium https://helm.cilium.io
helm install cilium cilium/cilium -n kube-system \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=dev-control-plane \
  --set k8sServicePort=6443 \
  --set ipam.mode=kubernetes \
  --set gatewayAPI.enabled=true \
  --set gatewayAPI.hostNetwork.enabled=true

```

## Flux

```bash
flux-operator create secret basic-auth git-creds \
  --namespace=flux-system --username=<user> --password=<token>

flux-operator install -f flux-instance.yaml
```
