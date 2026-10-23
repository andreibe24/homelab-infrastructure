# Open WebUI RAG document sync

Documents are stored in `apps/openwebui/rag/documents/`. The CronJob syncs
these files to the Open WebUI knowledge base **Homelab Documents** every
15 minutes. Add each document to `configMapGenerator.files` in
`kustomization.yaml`; documents must be flat files in this directory, and the
generated ConfigMap must stay below Kubernetes' 1 MiB limit.

The first sync requires an Open WebUI API key from an administrator account.
Create the `open-webui-rag-api` Secret in the `open-webui` namespace without
committing the key to Git:

```sh
kubectl create secret generic open-webui-rag-api \
  --namespace open-webui \
  --from-file=token=/secure/path/to/open-webui-api-key
```

The sync job creates the knowledge base if it does not exist, then uses
Open WebUI's file and knowledge APIs to add, update, and remove documents
incrementally. Configure an embedding model in Open WebUI before syncing
documents so they can be indexed for retrieval.
