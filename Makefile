BASE_IMAGE ?= lapig/pasto-legal:base

.PHONY: base base-push up down

# Build the heavy base image locally (needed when pyproject.toml/uv.lock change).
base:
	docker build -f docker/Dockerfile-Base -t $(BASE_IMAGE) .

# Build and publish the base image to Docker Hub.
base-push: base
	docker push $(BASE_IMAGE)

# Start the development environment (pulls the base image if missing).
up:
	docker compose up

down:
	docker compose down
