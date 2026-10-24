# Project 357: Documentation Index

Welcome to the authoritative documentation suite for **Project 357: Kubernetes-Based Auto-Scaling Framework for Cloud Applications (KubePilot)**.

This directory contains complete technical references, operational procedures, architecture specifications, API documentation, and benchmark evaluations for the KubePilot project.

---

## Documentation Structure

```
documents/
├── markdown/                     # Authoritative Markdown Technical Documentation
│   ├── PROJECT_OVERVIEW.md       # Executive summary, research motivation, scope & boundaries
│   ├── SYSTEM_ARCHITECTURE.md    # Control plane topology, sequence flows, data pipeline
│   ├── IMPLEMENTATION_DETAILS.md # Deep dive into code modules, classes, and algorithms
│   ├── SETUP_AND_EXECUTION.md    # Prerequisites, cluster provisioning, commands to run
│   ├── TESTING_AND_VERIFICATION.md # Test suite inventory, Pytest commands, acceptance checks
│   ├── EXPERIMENTS_AND_EVALUATION.md # Benchmark evaluation: Stable Workload & Sudden Traffic Spike
│   ├── API_REFERENCE.md          # REST API contracts, JSON schemas, endpoints & probes
│   └── TROUBLESHOOTING.md        # Real error diagnostics, recovery procedures & recovery scripts
│
├── pdf/                          # Formatted Publication Reference Documents
│   ├── PROJECT_REFERENCE.pdf     # Consolidated executive and technical reference manual
│   ├── SYSTEM_ARCHITECTURE.pdf   # Complete architecture diagram & control plane guide
│   ├── SETUP_AND_EXECUTION.pdf   # Cluster setup, provisioning, and operations guide
│   └── TESTING_AND_VERIFICATION.pdf # Test suite catalog and validation report
│
└── archive/                      # Historical Records and Previous Audit Reports
    ├── ARCHITECTURE_AND_UI_FLOW.md
    ├── EXECUTION_FLOW.md
    ├── EXPERIMENTATION_AUDIT_REPORT.md
    ├── EXPERIMENTATION_AUDIT_REPORT.pdf
    ├── IMPLEMENTATION_ROADMAP.md
    ├── MINIKUBE_PROMETHEUS_TELEMETRY_GUIDE.md
    ├── MINIKUBE_PROMETHEUS_TELEMETRY_GUIDE.pdf
    ├── MODULE_CONTRACTS.md
    ├── PROJECT_357_REVIEW.pdf
    ├── PROJECT_BASELINE.md
    ├── UI_COMPONENTS.md
    └── VERIFICATION_REPORT.md
```

---

## Markdown Reference Library

| Document | Primary Audience | Key Contents |
| :--- | :--- | :--- |
| [**`PROJECT_OVERVIEW.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/PROJECT_OVERVIEW.md) | Leadership / Operators | Problem statement, native HPA limitations, research motivation, high availability goals, system boundaries. |
| [**`SYSTEM_ARCHITECTURE.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/SYSTEM_ARCHITECTURE.md) | Architects / Engineers | Control plane topology, sequence diagrams, reconciliation loop, PRAH arbitration flow, state machine. |
| [**`IMPLEMENTATION_DETAILS.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/IMPLEMENTATION_DETAILS.md) | Developers / Reviewers | Module-by-module walkthrough (`controller/`, `dashboard/`, `policies/`), classes, methods, and configurations. |
| [**`SETUP_AND_EXECUTION.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/SETUP_AND_EXECUTION.md) | Operators / DevOps | Step-by-step setup: Minikube provisioning, Prometheus setup, running the dashboard, executing experiments. |
| [**`TESTING_AND_VERIFICATION.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/TESTING_AND_VERIFICATION.md) | QA / Reviewers | 102 automated tests across 9 test suites, coverage details, cluster acceptance checklists. |
| [**`EXPERIMENTS_AND_EVALUATION.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/EXPERIMENTS_AND_EVALUATION.md) | Researchers / Reviewers | Empirical benchmarking: Stable Workload vs. Sudden Traffic Spike, empirical tables, survivability analysis. |
| [**`API_REFERENCE.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/API_REFERENCE.md) | API Consumers / UI Devs | REST API endpoint catalog, JSON schemas, query parameters, health (`/healthz`) and readiness (`/readyz`) probes. |
| [**`TROUBLESHOOTING.md`**](file:///c:/Users/SRIRAM/design_project/documents/markdown/TROUBLESHOOTING.md) | Support / Operators | Diagnostic workflows for cluster disconnects, Prometheus failures, cooldown blocks, port collisions, and HPA conflicts. |

---

## Formatted PDF References

High-resolution printable PDF documents are compiled and available in `documents/pdf/`:
* [**`PROJECT_REFERENCE.pdf`**](file:///c:/Users/SRIRAM/design_project/documents/pdf/PROJECT_REFERENCE.pdf) — Comprehensive overview of Project 357, PRAH algorithm, objectives, and empirical findings.
* [**`SYSTEM_ARCHITECTURE.pdf`**](file:///c:/Users/SRIRAM/design_project/documents/pdf/SYSTEM_ARCHITECTURE.pdf) — In-depth architectural blueprint and data interaction diagrams.
* [**`SETUP_AND_EXECUTION.pdf`**](file:///c:/Users/SRIRAM/design_project/documents/pdf/SETUP_AND_EXECUTION.pdf) — Complete operational manual for cluster provisioning and deployment.
* [**`TESTING_AND_VERIFICATION.pdf`**](file:///c:/Users/SRIRAM/design_project/documents/pdf/TESTING_AND_VERIFICATION.pdf) — Complete test catalog, verification matrices, and live cluster acceptance results.
