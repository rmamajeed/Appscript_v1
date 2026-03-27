# Setup Guide: Hourly Cron Job for RFQ Processor

This guide explains how to schedule your RFQ Processor to run automatically every hour on your Linux machine.

## Prerequisites
1.  **Script Location**: `/media/emsi/New Volume/Python/Appscript_v1/run_rfq.sh`
2.  **Permissions**: The script must be executable. I have already run `chmod +x` on it for you.

---

## Step 1: Open your Crontab
Run the following command in your terminal to edit your user's cron table:

```bash
crontab -e
```

> [!NOTE]
> If it's your first time running this, it might ask you to choose an editor. Choose `nano` (usually option 1) if you're not sure.

---

## Step 2: Add the Hourly Schedule
Scroll to the very bottom of the file and add this exact line:

```bash
0 * * * * /bin/bash "/media/emsi/New Volume/Python/Appscript_v1/run_rfq.sh"
```

### Explanation of the syntax:
- `0` (Minute 0): Run at the start of every hour.
- `* * * *`: Run every day, every month, every day of the week.
- `/bin/bash`: Uses the Bash shell to execute the script.
- `"..."`: The full path to your script (with quotes to handle the space in "New Volume").

---

## Step 3: Save and Exit
- If you are using **Nano**:
    1. Press `Ctrl + O` (then Enter) to Save.
    2. Press `Ctrl + X` to Exit.
- The terminal should say: `crontab: installing new crontab`.

---

## Step 4: Verify the Setup
To confirm that your crontab was saved correctly, run:

```bash
crontab -l
```

Your new line should appear at the bottom.

---

## Monitoring and Logs
The script is configured to log everything to a file named `cron_run.log` inside your project folder. You can check it anytime to see the results of the automated runs:

```bash
tail -f "/media/emsi/New Volume/Python/Appscript_v1/cron_run.log"
```
