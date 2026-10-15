# Instructions

## Kind
```bash
kind create cluster --name dev --config kind.yaml \
  --kubeconfig ~/.kube/configs/dev-cluster.yaml

kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml

helm upgrade --install cilium oci://quay.io/cilium/charts/cilium:1.20.2 \
  --namespace kube-system \
  --reuse-values \
  --set kubeProxyReplacement=true \
  --set k8sServiceHost=dev-control-plane \
  --set k8sServicePort=6443 \
  --set ipam.mode=kubernetes \
  --set gatewayAPI.enabled=true \
  --set gatewayAPI.hostNetwork.enabled=true \
  --set operator.replicas=1
```

## Flux

```bash
kubectl create ns flux-system

flux-operator create secret basic-auth git-creds \
  --namespace=flux-system --username=<user> --password=<token>

flux-operator install -f flux-instance.yaml
```
