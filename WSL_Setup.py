# 1. Open WSL2 terminal
wsl

# 2. Navigate to project
cd /mnt/c/Users/2171176/Documents/Python/Appscript

# 3. Install ALL system dependencies upfront
sudo apt update && sudo apt install -y \
    python3-pip python3-venv build-essential \
    libcairo2-dev libpango-1.0-0 libpango1.0-dev \
    libgdk-pixbuf2.0-dev libffi-dev libssl-dev pkg-config

# 4. Create venv
python3 -m venv venv_linux
source venv_linux/bin/activate

# 5. Upgrade pip
pip install --upgrade pip

# 6. Install requirements
pip install -r requirements.txt

# 7. Run OAuth setup
python auth_setup.py

# 8. Test run
python main.py
