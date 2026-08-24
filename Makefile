.PHONY: up down logs build test backup

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
