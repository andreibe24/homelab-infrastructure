variable "REGISTRY" {
  default = "ghcr.io/andreibe24/homelab-infrastructure"
}

variable "TAGS" {
  default = "dev"
}

target "backend" {
  context    = "."
  dockerfile = "Dockerfile.backend"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags = [
    for tag in split(",", TAGS) :
    "${REGISTRY}/webapp-django-vite-backend:${tag}"
  ]
}

target "frontend" {
  context    = "."
  dockerfile = "Dockerfile.frontend"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags = [
    for tag in split(",", TAGS) :
    "${REGISTRY}/webapp-django-vite-frontend:${tag}"
  ]
}

target "rag" {
  context    = "."
  dockerfile = "Dockerfile.rag"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags = [
    for tag in split(",", TAGS) :
    "${REGISTRY}/webapp-django-vite-rag:${tag}"
  ]
}

group "default" {
  targets = ["backend", "frontend", "rag"]
}
