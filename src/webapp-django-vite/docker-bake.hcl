variable "REGISTRY" {
  default = "ghcr.io/andreibe24/homelab-infrastructure"
}

variable "TAG" {
  default = "dev"
}

function "tags" {
  params = [image]
  result = [
    for tag in (TAG == "dev" ? [TAG] : [TAG, "dev"]) :
    "${REGISTRY}/${image}:${tag}"
  ]
}

target "backend" {
  context    = "."
  dockerfile = "Dockerfile.backend"
  tags       = tags("webapp-django-vite-backend")
}

target "frontend" {
  context    = "."
  dockerfile = "Dockerfile.frontend"
  tags       = tags("webapp-django-vite-frontend")
}

group "default" {
  targets = ["backend", "frontend"]
}
