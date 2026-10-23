# Homelab RAG sample

This sample document is synced to the Open WebUI knowledge base named
**Homelab Documents**. Replace it or add Markdown documents in this directory
to provide information for retrieval-augmented generation.

## How syncing works

A Kubernetes CronJob runs every 15 minutes. It compares the files mounted from
this directory with the knowledge base, then uploads new or changed files and
removes files that were deleted from the repository.
