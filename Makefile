.PHONY: test dashboard controller docker-build minikube-up minikube-deploy clean help

PYTHON ?= python

help:
	@echo "Kubernetes Auto-Scaling Framework (Project 357)"
	@echo "Alliance University, Bengaluru"
	@echo "-----------------------------------------------"
	@echo "make test            - Run all unit and safety tests via pytest"
	@echo "make dashboard       - Start the web dashboard locally (http://localhost:5000)"
	@echo "make controller      - Start the PRAH controller locally in dry-run mode"
	@echo "make minikube-up     - Start local Minikube cluster"
	@echo "make minikube-deploy - Deploy framework manifests to Minikube"
	@echo "make clean           - Remove temporary test and cache files"

test:
	$(PYTHON) -m pytest tests/ -v

dashboard:
	$(PYTHON) -m dashboard.app

controller:
	$(PYTHON) -m controller.main

minikube-up:
	minikube start --cpus=2 --memory=4096 --driver=docker

minikube-deploy:
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/policies-configmap.yaml
	kubectl apply -f k8s/controller-rbac.yaml
	kubectl apply -f app/sample-app.yaml
	kubectl apply -f monitoring/prometheus-config.yaml
	kubectl apply -f monitoring/prometheus-deployment.yaml
	kubectl apply -f k8s/controller-deployment.yaml
	kubectl apply -f k8s/dashboard-deployment.yaml

clean:
	rm -rf __pycache__ .pytest_cache htmlcov .coverage
