.PHONY: help up down infra migrate revision psql logs install

help:
	@echo "QuorumNexus — local dev"
	@echo "  make install   Install the package + dev deps into the active venv"
	@echo "  make infra      Start db, redis, minio (detached)"
	@echo "  make migrate    Apply Alembic migrations (in a container)"
	@echo "  make up          infra + migrate"
	@echo "  make down        Stop the stack"
	@echo "  make psql        Open psql against the local db"
	@echo "  make revision m='msg'   Create a new empty migration"

install:
	pip install -e ".[dev]"

infra:
	docker compose up -d db redis minio

migrate:
	docker compose run --rm migrate

up: infra migrate

down:
	docker compose down

logs:
	docker compose logs -f

psql:
	docker compose exec db psql -U $${DB_USER:-postgres} -d $${DB_NAME:-quorum_nexus}

revision:
	alembic revision -m "$(m)"
