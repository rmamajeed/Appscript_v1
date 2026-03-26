# RFQ Processor — Setup Guide

This guide walks you through setting up and running the RFQ email automation system from scratch. Follow the section that matches your account type.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Get the Code](#2-get-the-code)
3. [GCP Project Setup (required for both account types)](#3-gcp-project-setup)
4. [Local Setup — Personal Gmail Account](#4-local-setup--personal-gmail-account)
5. [Local Setup — Google Workspace Account](#5-local-setup--google-workspace-account)
6. [Configure Environment Variables](#6-configure-environment-variables)
7. [Run Locally](#7-run-locally)
8. [Deploy to Google Cloud Run](#8-deploy-to-google-cloud-run)
9. [Set Up Automated Scheduling (Cloud Scheduler)](#9-set-up-automated-scheduling-cloud-scheduler)
10. [Set Up CI/CD with GitHub Actions](#10-set-up-cicd-with-github-actions)
11. [Verify Everything is Working](#11-verify-everything-is-working)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

Install the following before starting:

- **Python 3.11+** — https://www.python.org/downloads/
- **Git** — https://git-scm.com/
- **Docker Desktop** — https://www.docker.com/products/docker-desktop/ (required for Cloud Run deployment)
- **Google Cloud SDK (gcloud CLI)** — https://cloud.google.com/sdk/docs/install
- A **Google Cloud Platform (GCP) account** — https://console.cloud.google.com/

After installing the gcloud CLI, log in:

```bash
gcloud auth login
gcloud auth application-default login
```

---

## 2. Get the Code

```bash
git clone <your-repo-url>
cd <repo-folder>
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Copy the environment variables template:

```bash
cp .env.example .env
```

---

## 3. GCP Project Setup

These steps are required regardless of account type.

### 3.1 Create or select a GCP project

```bash
gcloud projects create YOUR_PROJECT_ID --name="RFQ Processor"
gcloud config set project YOUR_PROJECT_ID
```

Or use an existing project:

```bash
gcloud config set project YOUR_EXISTING_PROJECT_ID
```

### 3.2 Enable required APIs

```bash
gcloud services enable \
  gmail.googleapis.com \
  drive.googleapis.com \
  sheets.googleapis.com \
  secretmanager.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  iam.googleapis.com
```

### 3.3 Get your Drive Folder ID and Sheet ID

- **PARENT_FOLDER_ID**: Open the target Google Drive folder in your browser. The ID is the last segment of the URL:
  `https://drive.google.com/drive/folders/`**`1UYCwSdNaWQ7_TJX4P_cJvgNmExtrkcFr`**

- **SHEET_ID**: Open the master Google Sheet. The ID is in the URL between `/d/` and `/edit`:
  `https://docs.google.com/spreadsheets/d/`**`1AQQK7xK-fY3xfGXJJSpCk-Wvl39IS2-NXwuVlO10OwM`**`/edit`

### 3.4 Get a Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API key**
3. Copy the key — you will add it to your `.env` file

---

## 4. Local Setup — Personal Gmail Account

Use this section if you are using a `@gmail.com` account or any personal Google account (not a Google Workspace / G Suite account).

This method uses **OAuth2** — you log in once in a browser and a `token.json` file is saved locally. The script auto-refreshes the token on every run.

### 4.1 Create an OAuth2 Desktop App credential in GCP

1. Go to **GCP Console → APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. If prompted to configure the consent screen:
   - Choose **External**
   - Fill in App name (e.g. "RFQ Processor") and your email
   - Under **Scopes**, add:
     - `https://www.googleapis.com/auth/gmail.modify`
     - `https://www.googleapis.com/auth/drive`
     - `https://www.googleapis.com/auth/spreadsheets`
   - Under **Test users**, add your Gmail address
   - Save
4. Back at Create Credentials → OAuth client ID:
   - Application type: **Desktop app**
   - Name: `RFQ Processor Local`
   - Click **Create**
5. Click **Download JSON**
6. Rename the downloaded file to `credentials.json` and place it in the project folder

### 4.2 Run the one-time login script

```bash
python auth_setup.py
```

This opens a browser window. Log in with the Gmail account the script should read from and click **Allow**. A `token.json` file is saved in the project folder. You do not need to repeat this step unless you delete `token.json`.

### 4.3 Update your .env

Open `.env` and fill in:

```
PARENT_FOLDER_ID=<your Drive folder ID>
SHEET_ID=<your Sheet ID>
GMAIL_USER_EMAIL=you@gmail.com
GEMINI_API_KEY=<your Gemini API key>
```

Leave the `SERVICE_ACCOUNT_*` lines empty or commented out. The script will automatically use `token.json`.

---

## 5. Local Setup — Google Workspace Account

Use this section if you are using a Google Workspace (formerly G Suite) account (`@yourcompany.com`). This method uses a **Service Account with Domain-Wide Delegation**, which allows the script to impersonate a user without requiring an interactive browser login.

### 5.1 Create a Service Account

1. Go to **GCP Console → IAM & Admin → Service Accounts**
2. Click **Create Service Account**
   - Name: `rfq-processor-sa`
   - ID: `rfq-processor-sa` (auto-filled)
   - Click **Create and Continue**
3. Under **Grant this service account access to project**, skip (no project-level roles needed)
4. Click **Done**

### 5.2 Enable Domain-Wide Delegation on the Service Account

1. Click on the newly created service account
2. Go to the **Advanced settings** section
3. Under **Domain-wide delegation**, click **Enable G Suite Domain-wide Delegation**
4. Note the **Client ID** shown (you will need it in the next step)
5. Click **Save**

### 5.3 Authorize the Service Account in Google Workspace Admin

> This step requires Google Workspace Admin access.

1. Go to **Google Workspace Admin Console** → **Security → Access and data control → API Controls → Manage Domain-Wide Delegation**
2. Click **Add new**
3. Enter the **Client ID** from step 5.2
4. In **OAuth Scopes**, enter these comma-separated scopes:
   ```
   https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/spreadsheets
   ```
5. Click **Authorize**

### 5.4 Download the Service Account Key

1. Back in **GCP Console → IAM & Admin → Service Accounts**, click your service account
2. Go to the **Keys** tab
3. Click **Add Key → Create new key**
4. Choose **JSON** → **Create**
5. The key file downloads automatically. Keep it safe — treat it like a password.
6. For local testing, note the file path (e.g. `C:/keys/rfq-processor-sa-key.json`)

### 5.5 Update your .env

Open `.env` and fill in:

```
PARENT_FOLDER_ID=<your Drive folder ID>
SHEET_ID=<your Sheet ID>
GMAIL_USER_EMAIL=user@yourcompany.com
GEMINI_API_KEY=<your Gemini API key>
SERVICE_ACCOUNT_KEY_PATH=C:/keys/rfq-processor-sa-key.json
```

---

## 6. Configure Environment Variables

Open `.env` and verify all values are set. Key variables:

| Variable | Description | Example |
|---|---|---|
| `PARENT_FOLDER_ID` | Google Drive folder where RFQ subfolders are created | `1UYCwSdNaWQ7...` |
| `SHEET_ID` | Master Google Sheet ID | `1AQQK7xK-fY3x...` |
| `GMAIL_USER_EMAIL` | Gmail address the script reads from | `you@gmail.com` |
| `GEMINI_API_KEY` | Gemini API key from AI Studio | `AIza...` |
| `SEARCH_QUERY` | Gmail search filter | `subject:RFQ -label:PROCESSED_BY_BOT` |
| `PROCESSED_LABEL_NAME` | Label applied after processing | `PROCESSED_BY_BOT` |
| `BATCH_SIZE` | Max threads to process per run | `20` |
| `SLEEP_BETWEEN_THREADS` | Seconds to wait between threads (avoids Gemini quota limits) | `30` |

---

## 7. Run Locally

```bash
python main.py
```

**What to expect on a successful run:**

```
2024-01-15 10:00:01 [INFO] Auth: using OAuth2 token from 'token.json'
2024-01-15 10:00:02 [INFO] Found 3 new thread(s) to process.
2024-01-15 10:00:03 [INFO] Processing: 'RFQ-GEN-1234 - Motor Insurance'
2024-01-15 10:00:15 [INFO] Renamed folder to: RFQ-GEN-1234 - ACME CORPORATION
2024-01-15 10:00:16 [INFO] Successfully processed and labeled: 'RFQ-GEN-1234 - Motor Insurance'
2024-01-15 10:00:16 [INFO] Sleeping 30s before next thread...
...
2024-01-15 10:02:45 [INFO] Run complete.
```

To test with just one thread first:

```bash
BATCH_SIZE=1 python main.py
```

---

## 8. Deploy to Google Cloud Run

### 8.1 Create a runtime Service Account (if not already done)

If you are using a personal Gmail account, you still need a **separate** Service Account for Cloud Run to call GCP APIs (Secret Manager). The impersonation approach used for Workspace does not apply here — the OAuth2 token for personal Gmail must be stored in Secret Manager separately.

> **Personal Gmail on Cloud Run**: This is not natively supported in a headless environment since OAuth2 requires an initial browser login. The recommended approach for production is to use a Google Workspace account with Domain-Wide Delegation. If you must use personal Gmail on Cloud Run, generate `token.json` locally and store its contents as a Secret Manager secret named `OAUTH_TOKEN_JSON`, then modify `build_credentials()` to read it.

For **Google Workspace** accounts, use the same service account created in section 5.

### 8.2 Create an Artifact Registry Docker repository

```bash
gcloud artifacts repositories create rfq-automation \
  --repository-format=docker \
  --location=asia-southeast1 \
  --description="RFQ Processor Docker images"
```

Replace `asia-southeast1` with your preferred region. Consistent use of the same region throughout reduces latency and egress costs.

### 8.3 Store secrets in Secret Manager

Add each secret individually:

```bash
# Gemini API key
echo -n "YOUR_GEMINI_API_KEY" | \
  gcloud secrets create GEMINI_API_KEY --data-file=-

# Service Account JSON (paste the full contents of the key JSON file as one line)
cat /path/to/rfq-processor-sa-key.json | \
  gcloud secrets create SERVICE_ACCOUNT_JSON --data-file=-

# Other configuration
echo -n "user@yourcompany.com" | \
  gcloud secrets create GMAIL_USER_EMAIL --data-file=-

echo -n "1UYCwSdNaWQ7_TJX4P_cJvgNmExtrkcFr" | \
  gcloud secrets create PARENT_FOLDER_ID --data-file=-

echo -n "1AQQK7xK-fY3xfGXJJSpCk-Wvl39IS2-NXwuVlO10OwM" | \
  gcloud secrets create SHEET_ID --data-file=-

echo -n "subject:RFQ -label:PROCESSED_BY_BOT" | \
  gcloud secrets create SEARCH_QUERY --data-file=-

echo -n "PROCESSED_BY_BOT" | \
  gcloud secrets create PROCESSED_LABEL_NAME --data-file=-

echo -n "20" | \
  gcloud secrets create BATCH_SIZE --data-file=-
```

### 8.4 Grant the Service Account access to secrets

```bash
SA_EMAIL="rfq-processor-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"

for SECRET in GEMINI_API_KEY SERVICE_ACCOUNT_JSON GMAIL_USER_EMAIL \
              PARENT_FOLDER_ID SHEET_ID SEARCH_QUERY \
              PROCESSED_LABEL_NAME BATCH_SIZE; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/secretmanager.secretAccessor"
done
```

### 8.5 Build and push the Docker image manually (first time)

```bash
PROJECT_ID="YOUR_PROJECT_ID"
REGION="asia-southeast1"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/rfq-automation/rfq-processor"

gcloud auth configure-docker $REGION-docker.pkg.dev

docker build -t $IMAGE:latest .
docker push $IMAGE:latest
```

### 8.6 Create the Cloud Run Job

```bash
gcloud run jobs create rfq-processor-job \
  --image=$IMAGE:latest \
  --region=$REGION \
  --service-account=$SA_EMAIL \
  --set-secrets="\
    GEMINI_API_KEY=GEMINI_API_KEY:latest,\
    SERVICE_ACCOUNT_JSON=SERVICE_ACCOUNT_JSON:latest,\
    GMAIL_USER_EMAIL=GMAIL_USER_EMAIL:latest,\
    PARENT_FOLDER_ID=PARENT_FOLDER_ID:latest,\
    SHEET_ID=SHEET_ID:latest,\
    SEARCH_QUERY=SEARCH_QUERY:latest,\
    PROCESSED_LABEL_NAME=PROCESSED_LABEL_NAME:latest,\
    BATCH_SIZE=BATCH_SIZE:latest" \
  --task-timeout=3600 \
  --max-retries=2
```

### 8.7 Run the job manually to verify

```bash
gcloud run jobs execute rfq-processor-job \
  --region=$REGION \
  --wait
```

Check the logs:

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=rfq-processor-job" \
  --limit=50 \
  --format="table(timestamp, textPayload)"
```

---

## 9. Set Up Automated Scheduling (Cloud Scheduler)

This triggers the Cloud Run Job automatically on a schedule.

### 9.1 Create a scheduler Service Account

Create a separate, minimal-permission service account just for invoking the job:

```bash
gcloud iam service-accounts create rfq-scheduler-sa \
  --display-name="RFQ Scheduler Invoker"

SCHEDULER_SA="rfq-scheduler-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$SCHEDULER_SA" \
  --role="roles/run.invoker"
```

### 9.2 Create the Cloud Scheduler job

The following runs the processor every 2 hours:

```bash
gcloud scheduler jobs create http rfq-processor-schedule \
  --location=$REGION \
  --schedule="0 */2 * * *" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/YOUR_PROJECT_ID/jobs/rfq-processor-job:run" \
  --http-method=POST \
  --oauth-service-account-email=$SCHEDULER_SA \
  --time-zone="Asia/Singapore"
```

**Common schedule options:**

| Schedule | Cron expression |
|---|---|
| Every 2 hours | `0 */2 * * *` |
| Every 4 hours | `0 */4 * * *` |
| Twice a day (9am and 5pm) | `0 9,17 * * *` |
| Once a day at 8am | `0 8 * * *` |
| Weekdays only at 8am | `0 8 * * 1-5` |

Change `Asia/Singapore` to your timezone. Find valid timezone names at https://en.wikipedia.org/wiki/List_of_tz_database_time_zones

### 9.3 Test the scheduler manually

```bash
gcloud scheduler jobs run rfq-processor-schedule --location=$REGION
```

---

## 10. Set Up CI/CD with GitHub Actions

Every push to `main` will automatically build a new Docker image and update the Cloud Run Job.

### 10.1 Create a deployment Service Account

This is a separate account with minimal permissions, used only by GitHub Actions for CI/CD:

```bash
gcloud iam service-accounts create deploy-sa \
  --display-name="RFQ Processor Deploy SA"

DEPLOY_SA="deploy-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com"

# Allow pushing images to Artifact Registry
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$DEPLOY_SA" \
  --role="roles/artifactregistry.writer"

# Allow updating the Cloud Run Job
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$DEPLOY_SA" \
  --role="roles/run.developer"

# Allow reading Secret Manager secrets (needed for --set-secrets in the deploy step)
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:$DEPLOY_SA" \
  --role="roles/secretmanager.viewer"

# Allow the deploy SA to act as the runtime SA (required for --service-account in job update)
gcloud iam service-accounts add-iam-policy-binding $SA_EMAIL \
  --member="serviceAccount:$DEPLOY_SA" \
  --role="roles/iam.serviceAccountUser"
```

### 10.2 Set up Workload Identity Federation (recommended — keyless)

This allows GitHub Actions to authenticate to GCP without storing any long-lived keys in GitHub.

```bash
# Create a Workload Identity Pool
gcloud iam workload-identity-pools create github-pool \
  --location=global \
  --display-name="GitHub Actions Pool"

# Create an OIDC provider within the pool
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# Get the full pool name
POOL_NAME=$(gcloud iam workload-identity-pools describe github-pool \
  --location=global \
  --format="value(name)")

# Allow GitHub Actions from your repo to impersonate the deploy SA
gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/$POOL_NAME/attribute.repository/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME"

# Get the WIF provider resource name (you will add this to GitHub Secrets)
gcloud iam workload-identity-pools providers describe github-provider \
  --location=global \
  --workload-identity-pool=github-pool \
  --format="value(name)"
```

### 10.3 Add GitHub Secrets

In your GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret**.

Add these secrets:

| Secret name | Value |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `WIF_PROVIDER` | Output of the last `gcloud` command above (full resource name) |
| `WIF_SERVICE_ACCOUNT` | `deploy-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com` |

> **Alternative (simpler but less secure):** If you prefer to skip WIF, you can create a JSON key for `deploy-sa`, base64-encode it, and store it as a `GCP_SA_KEY` secret. Then edit `.github/workflows/deploy.yml` to use `credentials_json: ${{ secrets.GCP_SA_KEY }}` instead of the WIF block.

### 10.4 Update the deploy.yml region

Open `.github/workflows/deploy.yml` and verify the `REGION` value matches the region you used when creating the Artifact Registry repo and Cloud Run Job:

```yaml
env:
  REGION: asia-southeast1   # Change this if you used a different region
```

### 10.5 Push to trigger the first deployment

```bash
git add .
git commit -m "Initial deployment"
git push origin main
```

Watch the workflow at `https://github.com/YOUR_USERNAME/YOUR_REPO/actions`.

---

## 11. Verify Everything is Working

After a full run (local or Cloud Run), check the following:

**Google Drive:**
- [ ] A new subfolder was created inside your parent folder (named `RFQ-ID - CLIENT NAME`)
- [ ] Email PDFs are saved inside the subfolder (`Email_YYYY-MM-DD_...pdf`)
- [ ] Attachments are saved inside the subfolder (`Att_YYYY-MM-DD_...`)
- [ ] A `Timeline_RFQ-ID_CLIENT` spreadsheet exists inside the subfolder

**Google Sheets (master sheet):**
- [ ] A new row was added (or an existing row updated) with 15 columns of extracted data

**Gmail:**
- [ ] The processed thread has the `PROCESSED_BY_BOT` label applied
- [ ] The thread no longer appears in subsequent runs

**Cloud Run (production only):**
- [ ] Job execution shows exit code `0` in Cloud Run console
- [ ] No `ErrorLog_*.txt` files in Drive folders (or if present, review the contents)

---

## 12. Troubleshooting

**`No authentication credentials found`**
- Personal Gmail: Run `python auth_setup.py` first. Ensure `token.json` was created in the project folder.
- Workspace: Check that `SERVICE_ACCOUNT_KEY_PATH` in `.env` points to a valid file, or `SERVICE_ACCOUNT_JSON` is set.

**`Cannot access PARENT_FOLDER_ID`**
- The authenticated account (or service account) does not have access to the Drive folder.
- Personal Gmail: Share the folder with your Gmail address.
- Workspace SA: Share the folder with `rfq-processor-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com`.

**`403 insufficientPermissions` from Gmail/Drive/Sheets**
- The OAuth consent screen scopes or Domain-Wide Delegation scopes are incomplete.
- Re-check sections 4.1 (personal) or 5.3 (Workspace) and ensure all three scopes are listed.

**`429 RESOURCE_EXHAUSTED` from Gemini**
- Hit the daily API quota (500 requests/day on free tier).
- Reduce `BATCH_SIZE` or increase `SLEEP_BETWEEN_THREADS`.
- Upgrade to a paid Gemini API tier for higher limits.

**`cannot load library 'gobject-2.0-0'`**
- This is a weasyprint warning on Windows. It is handled automatically — the script falls back to xhtml2pdf. No action needed.

**PDF files are empty or corrupted**
- Usually caused by emails with no HTML body. The script falls back to `<pre>plain text</pre>` automatically.

**Timeline sheet duplicate created**
- This was a known bug (fixed). The sheet search is now RFQ-ID based, not name-based. If you see duplicates from before the fix, manually delete the older sheet in Drive.

**Cloud Run Job exits with code 1**
- Check logs: `gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=rfq-processor-job" --limit=50`
- Usually a missing secret or incorrect `PARENT_FOLDER_ID`/`SHEET_ID`.

**GitHub Actions failing at auth step**
- Verify `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` secrets are set correctly in GitHub.
- Ensure the `--member` principal in step 10.2 matches your exact GitHub username and repo name (case-sensitive).
