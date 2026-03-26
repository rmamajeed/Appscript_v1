# Getting OAuth Credentials (credentials.json)

This guide explains how to obtain the `credentials.json` file needed to authenticate with Google APIs (Gmail, Drive, Sheets).

## Prerequisites

- A Google account
- A Google Cloud Project (create one if you don't have it)
- Admin access to the GCP project

---

## Step 1: Go to Google Cloud Console

1. Open https://console.cloud.google.com/
2. Sign in with your Google account
3. You should see a dashboard with projects

---

## Step 2: Create or Select a GCP Project

**If you don't have a project:**
- Click the **Project dropdown** at the top
- Click **NEW PROJECT**
- Enter a name like `RFQ-Automation` or `RFQ-Processor`
- Click **CREATE**
- Wait for it to be created (1-2 minutes)

**If you have an existing project:**
- Click the **Project dropdown**
- Select the project you want to use

---

## Step 3: Enable Required APIs

Go to **APIs & Services → Library**

### Enable Gmail API
1. Search for **`Gmail API`**
2. Click it
3. Click **ENABLE**
4. Wait for it to finish

### Enable Google Drive API
1. Search for **`Google Drive API`**
2. Click it
3. Click **ENABLE**
4. Wait for it to finish

### Enable Google Sheets API
1. Search for **`Google Sheets API`**
2. Click it
3. Click **ENABLE**
4. Wait for it to finish

---

## Step 4: Create OAuth 2.0 Credentials

Go to **APIs & Services → Credentials**

1. Click **+ CREATE CREDENTIALS** (button at top)
2. Select **OAuth client ID**
3. If prompted, click **CONFIGURE CONSENT SCREEN**

### Configure OAuth Consent Screen (one-time)

1. Choose **User Type: External** (unless you're in Google Workspace, then choose **Internal**)
2. Click **CREATE**
3. Fill in the form:
   - **App name:** `RFQ Processor` (or your choice)
   - **User support email:** Your email
   - **Developer contact info:** Your email
4. Click **SAVE AND CONTINUE**

**Scopes Page:**
1. Click **ADD OR REMOVE SCOPES**
2. Search for and add:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/spreadsheets`
3. Click **UPDATE**
4. Click **SAVE AND CONTINUE** → **SAVE AND CONTINUE** again

**Summary Page:**
- Just click **BACK TO DASHBOARD**

### Create OAuth Client ID

Back on **Credentials** page:
1. Click **+ CREATE CREDENTIALS**
2. Select **OAuth client ID**
3. Choose **Application type: Desktop app**
4. Enter a name like `RFQ-Processor-Desktop`
5. Click **CREATE**

**Download the JSON:**
1. A popup appears with your **Client ID** and **Client Secret**
2. Click the **DOWNLOAD** button (looks like ↓)
3. Save the file as **`credentials.json`** in your project folder:
   ```
   c:\Users\2171176\Documents\Python\Appscript\credentials.json
   ```

---

## Step 5: Verify the File

Your `credentials.json` should look like:

```json
{
  "installed": {
    "client_id": "140453880875-xxxxxx.apps.googleusercontent.com",
    "project_id": "rfq-automation",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "GOCSPX-xxxxx",
    "redirect_uris": ["http://localhost"]
  }
}
```

✅ **You're done!** Keep this file secure — don't commit it to git (it's in `.gitignore`).

---

## Step 6: Run Auth Setup

Once `credentials.json` is in your project folder:

```bash
python auth_setup.py
```

This will:
1. Open a browser
2. Ask you to log in with Gmail
3. Show a permission screen
4. Create `token.json` automatically once you approve

---

## Troubleshooting

### "credentials.json not found"
- Make sure you downloaded it from GCP and saved it in the project folder
- Filename must be exactly `credentials.json` (case-sensitive on Linux/Mac)

### "Invalid client" error
- Check that `credentials.json` is the correct file from GCP
- Make sure APIs are **ENABLED** (Gmail, Drive, Sheets)

### "Redirect URI mismatch"
- Go to **Credentials → OAuth Client ID → Edit**
- Add these to **Authorized redirect URIs:**
  - `http://localhost/`
  - `http://localhost:8080/`
  - `http://127.0.0.1/`
- Click **SAVE**

### Browser won't open
- Run: `python auth_setup.py 2>&1`
- Copy the URL that appears in the terminal
- Paste it manually into your browser
- Complete the login
- The script will detect it and save `token.json`

---

## Next Steps

Once you have `credentials.json` and `token.json`:

1. Copy `.env.example` → `.env`
2. Fill in:
   - `GEMINI_API_KEY` — from Google AI Studio
   - `PARENT_FOLDER_ID` — your Google Drive folder ID
   - `SHEET_ID` — your master sheet ID
   - Other config variables
3. Run:
   ```bash
   python main.py
   ```

---

## Security Notes

⚠️ **IMPORTANT:**
- `credentials.json` contains your OAuth Client Secret — keep it private
- Never commit it to git (it's in `.gitignore`)
- Never share it publicly
- `token.json` is your access token — also never commit it
- Both files are in `.gitignore` for protection

✅ **Sharing the repo:** You can safely share the repo — the sensitive files are excluded.
