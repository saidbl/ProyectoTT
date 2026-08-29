.PHONY: up down logs build test backup denue-sync denue-dry-run denue-logs

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

build:
	docker compose build

test:
	docker compose run --rm backend pytest -q

backup:
	bash scripts/backup.sh

denue-sync:
	docker compose run --rm denue-updater python update_denue_api.py

denue-dry-run:
	docker compose run --rm denue-updater python update_denue_api.py --dry-run

denue-logs:
	docker compose logs -f --tail=200 denue-updater

