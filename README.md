# Discourse-Auto-Deactivate-Users-by-REST-API

This project provides a Python script and maybe in the future a GitHub Actions workflow to force Discourse users to reverify their email addresses by deactivating accounts via the admin REST API.

Deactivation is the supported way in Discourse to require a fresh email confirmation at next login.

## Why?

Keep your community’s email list accurate

Catch abandoned/disposable addresses

Periodically verify real user engagement

## Getting Started — with a £1/month IONOS VPS

This setup assumes you just purchased the entry-level IONOS VPS (Ubuntu 24.04 recommended).

1. Prepare the VPS

### Update packages
sudo apt update && sudo apt upgrade -y

### Install Python and Git
sudo apt install -y python3 python3-venv python3-pip git

2. Clone this repository
git clone https://github.com/Ethsim12/Discourse-Auto-Deactivate-Users-by-REST-API.git
cd Discourse-Auto-Deactivate-Users-by-REST-API

3. Create a virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

4. Configure environment variables

Create a .env file with your Discourse API credentials:

```env
DISCOURSE_BASE_URL=https://forum.example.com
DISCOURSE_API_KEY=your_admin_api_key
DISCOURSE_API_USER=system
DRY_RUN=true
USER_FILTER=active
LAST_SEEN_BEFORE_DAYS=365
INCLUDE_TL=0,1
EXCLUDE_STAFF=true
```

⚠️ You need an admin API key. Generate this from your Discourse Admin → API.

5. Run the script

Dry-run (no changes yet):

```
source venv/bin/activate
python force_reverify.py
```

Switch `DRY_RUN=false` in `.env` to actually deactivate accounts.

### Optional: Run with GitHub Actions

You don’t need to keep the VPS online 24/7. You can instead let GitHub Actions run the script for you.

Fork this repository

Add DISCOURSE_BASE_URL, DISCOURSE_API_KEY, and DISCOURSE_API_USER as secrets in your fork (Settings → Secrets → Actions).

Use the provided workflow in .github/workflows/force-reverify.yml.

It can be triggered manually (workflow_dispatch) or on a schedule (cron).

## Safety Features

Dry-run mode by default

Skips staff, suspended, and staged accounts

Optional filters by trust level and inactivity period

Exponential backoff & Retry-After handling for API rate limits

## Example Usage

Deactivate all Trust Level 0 users inactive for 9+ months:

```
DRY_RUN=false
USER_FILTER=active
LAST_SEEN_BEFORE_DAYS=270
INCLUDE_TL=0
```

License

MIT — free to use, modify, and share.
