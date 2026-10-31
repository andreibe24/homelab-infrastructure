# LLM serving (Ollama)

Self-hosted LLM inference, the on-prem counterpart of managed model APIs.
`apps/llm-serving/` runs [Ollama](https://ollama.com) (CPU, no GPU required)
with a 10Gi PVC for model weights, and a Job that pulls `qwen2.5:0.5b`.

- Endpoint: `http://ollama.llm-serving.svc:11434` (OpenAI-compatible at `/v1`).
- Ingress allowed from the same namespace, `gateway` and `monitoring`.
- Try it:
  `kubectl -n llm-serving port-forward svc/ollama 11434` then
  `curl localhost:11434/v1/chat/completions -d '{"model":"qwen2.5:0.5b","messages":[{"role":"user","content":"hi"}]}'`
- The pull Job needs internet egress; change the model in
  `ollama-pull-model.job.yaml` (larger models need a higher memory limit).
- Natural next steps: route through agentgateway, point the RAG app at it, and
  track models with MLflow (branch `curly-spork`).
