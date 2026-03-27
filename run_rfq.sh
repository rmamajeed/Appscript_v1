#!/bin/bash
# run_rfq.sh - Automated runner for the RFQ Intelligence Processor
# This script is intended to be run by Crontab.

# 1. Navigate to the project directory
cd "/media/emsi/New Volume/Python/Appscript_v1"

# 2. Activate the Linux virtual environment
# We use absolute paths to ensure Cron finds everything correctly.
source "/media/emsi/New Volume/Python/Appscript_v1/venv_linux/bin/activate"

# 3. Run the Python processor
# Output is appended to cron_run.log for auditing.
python3 main.py >> cron_run.log 2>&1
