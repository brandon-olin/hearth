.PHONY: api web migrate seed-app-projects seed-m1-subprojects update-m1-progress \
        service-install service-uninstall service-start service-stop service-restart service-status service-logs \
        bot-install bot-uninstall bot-start bot-stop bot-restart bot-status bot-logs \
        hook-install hook-uninstall sync-todos \
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

# ── Telegram bot ──────────────────────────────────────────────────────────────

BOT_LABEL   = com.lifedashboard.bot
BOT_PLIST   = $(HOME)/Library/LaunchAgents/$(BOT_LABEL).plist
LOG_DIR     = $(HOME)/Library/Logs/LifeDashboard
APP_DIR    := $(shell pwd)

bot-install:
	@echo "── Installing Hearth bot ──"
	@# Install python-telegram-bot into the API venv
	api/.venv/bin/pip install -q "python-telegram-bot>=20.0"
	@# Generate the run script from template
	@sed \
	  -e "s|{{APP_DIR}}|$(APP_DIR)|g" \
	  -e "s|{{LOG_DIR}}|$(LOG_DIR)|g" \
	  infra/scripts/run-bot.sh.tpl > infra/scripts/run-bot.sh
	@chmod +x infra/scripts/run-bot.sh
	@echo "  ✓ Generated infra/scripts/run-bot.sh"
	@# Generate and load the launchd plist
	@mkdir -p "$(LOG_DIR)"
	@sed \
	  -e "s|{{APP_DIR}}|$(APP_DIR)|g" \
	  -e "s|{{LOG_DIR}}|$(LOG_DIR)|g" \
	  infra/launchd/com.lifedashboard.bot.plist.tpl > "$(BOT_PLIST)"
	@launchctl unload "$(BOT_PLIST)" 2>/dev/null || true
	@launchctl load -w "$(BOT_PLIST)"
	@echo "  ✓ Loaded $(BOT_LABEL)"
	@echo ""
	@echo "Bot installed and running. Logs: make bot-logs"

bot-uninstall:
	@launchctl unload "$(BOT_PLIST)" 2>/dev/null && echo "  ✓ Unloaded $(BOT_LABEL)" || echo "  ○ Not loaded"
	@rm -f "$(BOT_PLIST)" infra/scripts/run-bot.sh

bot-start:
	@launchctl start "$(BOT_LABEL)" && echo "  ✓ Started $(BOT_LABEL)" || echo "  ○ Could not start (already running?)"

bot-stop:
	@launchctl stop "$(BOT_LABEL)" && echo "  ✓ Stopped $(BOT_LABEL)" || echo "  ○ Could not stop"

bot-restart: bot-stop
	@sleep 2
	@$(MAKE) bot-start

bot-status:
	@launchctl list | awk 'BEGIN{found=0} /$(BOT_LABEL)/{found=1; if($$1!="-") print "  ● $(BOT_LABEL)  running (PID "$$1")"; else print "  ○ $(BOT_LABEL)  stopped (last exit: "$$2")"} END{if(!found) print "  ○ $(BOT_LABEL)  not registered"}'

bot-logs:
	@echo "Tailing bot logs (Ctrl-C to exit)…"
	@tail -f "$(LOG_DIR)/bot.log" "$(LOG_DIR)/bot.error.log" 2>/dev/null

# ── Hearth todo sync ──────────────────────────────────────────────────────────

sync-todos:
	@set -a && . infra/local.env && set +a && \
	  api/.venv/bin/python3.12 infra/scripts/sync-todos.py

hook-install:
	@echo "── Installing post-commit hook ──"
	@sed -e "s|{{APP_DIR}}|$(APP_DIR)|g" \
	  infra/scripts/post-commit.hook.tpl > .git/hooks/post-commit
	@chmod +x .git/hooks/post-commit
	@echo "  ✓ Installed .git/hooks/post-commit"
	@echo "  Todos will sync automatically after every git commit."
	@echo "  Make sure HEARTH_SYNC_EMAIL and HEARTH_SYNC_PASSWORD are set in infra/local.env"

hook-uninstall:
	@rm -f .git/hooks/post-commit && echo "  ✓ Removed .git/hooks/post-commit" || true

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
