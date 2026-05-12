.PHONY: api web migrate seed-app-projects seed-m1-subprojects update-m1-progress \
        service-install service-uninstall service-start service-stop service-restart service-status service-logs

api:
	cd api && .venv/bin/uvicorn life_dashboard.main:app --reload --port 8000

web:
	cd web && npm run dev

migrate:
	cd api && .venv/bin/alembic upgrade head

seed-app-projects:
	cd api && .venv/bin/python3.12 scripts/seed_app_projects.py

seed-m1-subprojects:
	cd api && .venv/bin/python3.12 scripts/seed_m1_subprojects.py

update-m1-progress:
	cd api && .venv/bin/python3.12 scripts/update_m1_progress.py

# ── Local install service management ──────────────────────────────────────────

service-install:
	./infra/scripts/service.sh install

service-uninstall:
	./infra/scripts/service.sh uninstall

service-start:
	./infra/scripts/service.sh start

service-stop:
	./infra/scripts/service.sh stop

service-restart:
	./infra/scripts/service.sh restart

service-status:
	./infra/scripts/service.sh status

service-logs:
	./infra/scripts/service.sh logs
