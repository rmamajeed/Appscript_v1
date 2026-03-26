# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An intelligent email automation system that processes RFQ (Request for Quote) emails from Gmail using Google's Gemini AI. It extracts structured business intelligence and organizes it into Google Drive folders and Google Sheets. Originally a Google Apps Script (`code.gs`), now migrated to Python for Google Cloud Run deployment.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# One-time OAuth2 setup (personal Gmail only)
python auth_setup.py

# Run the processor
python main.py

# Test with a single thread
BATCH_SIZE=1 python main.py
```

## Deployment

```bash
# Build and push Docker image
docker build -t rfq-processor:latest .
docker push asia-southeast1-docker.pkg.dev/PROJECT_ID/rfq-automation/rfq-processor:latest

# Execute Cloud Run job manually
gcloud run jobs execute rfq-processor-job --wait

# View logs
gcloud logging read "resource.type=cloud_run_job" --limit=50
```

GitHub Actions CI/CD (`.github/workflows/deploy.yml`) auto-deploys on push to main via Workload Identity Federation.

## Architecture

### Authentication (priority order)
1. OAuth2 token (`token.json`) — personal Gmail
2. Service Account key file — local Workspace testing
3. Service Account JSON string — Cloud Run via Secret Manager

### Processing Pipeline (`main.py`)
Each Gmail thread goes through: Search → Create/find Drive folder → Fetch existing context → Build email history → Save PDFs/attachments → Gemini AI extraction → Update master Sheet + Timeline dossier → Rename folder → Apply Gmail label

Key behaviors:
- **Error isolation**: Per-thread try/catch; failures are logged to Drive, other threads continue
- **Deduplication**: Folders found by RFQ ID substring, files checked before upload, sheet rows keyed by `date+sender+summary`
- **Stateful AI**: Existing sheet data passed to Gemini so updates merge with prior extractions rather than overwriting
- **Junk filter**: Inline images < 20KB (logos/signatures) are skipped

### Key Sections in `main.py`
| Lines | Section |
|-------|---------|
| 33–134 | Authentication (3-strategy with auto-refresh) |
| 184–292 | Gmail helpers (search, headers, bodies, attachments) |
| 298–416 | Drive helpers (folder find/create, file upload, PDF generation) |
| 510–712 | Sheets helpers (upsert master sheet, timeline dossier) |
| 719–789 | Gemini AI integration |
| 795–924 | Main processing loop |

### PDF Generation
- **Linux/Docker**: WeasyPrint (primary)
- **Windows**: xhtml2pdf (fallback for local development)

### Configuration
All configuration via environment variables. Copy `.env.example` → `.env` for local dev. In Cloud Run, secrets come from GCP Secret Manager (see `SETUP.md` for full list).

### Legacy Reference
`code.gs` is the original Google Apps Script kept for feature parity reference. When adding features, check `code.gs` first to understand the intended behavior.
