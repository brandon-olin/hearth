.PHONY: api web migrate seed-app-projects seed-m1-subprojects update-m1-progress \
        service-install service-uninstall service-start service-stop service-restart service-status service-logs \
        desktop desktop-dev desktop-api desktop-web

api:
	cd api && .venv/bin/uvicorn life_dashboard.main:app --reload --port 1339

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

# ── Desktop (Tauri) ────────────────────────────────────────────────────────────

# Full build: PyInstaller API binary + Next.js export + tauri build
desktop:
	chmod +x scripts/build-desktop.sh
	./scripts/build-desktop.sh

# Open Tauri dev window (re-uses last binary + web build for speed)
desktop-dev:
	chmod +x scripts/build-desktop.sh
	./scripts/build-desktop.sh --skip-api --skip-web --dev

# Rebuild only the PyInstaller API binary (e.g. after Python changes)
desktop-api:
	chmod +x scripts/build-desktop.sh
	./scripts/build-desktop.sh --skip-web

# Rebuild only the Next.js static export (e.g. after frontend changes)
desktop-web:
	chmod +x scripts/build-desktop.sh
	./scripts/build-desktop.sh --skip-api
