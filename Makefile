.PHONY: dev api web install

dev: ## Start both API and web dev servers
	@trap 'kill 0' SIGINT; \
	~/miniforge3/bin/uvicorn src.api.main:app --port 8000 --reload --reload-dir src & \
	(export NVM_DIR="$$HOME/.nvm" && . "$$NVM_DIR/nvm.sh" && cd web && npm run dev) & \
	wait

api: ## Start API only
	~/miniforge3/bin/uvicorn src.api.main:app --port 8000 --reload --reload-dir src

web: ## Start Next.js only
	export NVM_DIR="$$HOME/.nvm" && . "$$NVM_DIR/nvm.sh" && cd web && npm run dev

install: ## Install all dependencies
	~/miniforge3/bin/pip install -r requirements.txt
	export NVM_DIR="$$HOME/.nvm" && . "$$NVM_DIR/nvm.sh" && cd web && npm install
