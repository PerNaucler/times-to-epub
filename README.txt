====================================================================
ABOUT Times to EPUB Automation
====================================================================

This project automates downloading articles from The Times / Sunday Times (requires a valid subscription), converting them to EPUB format with Calibre, and emails the result to a Kindle device.

It is designed for personal use, running daily on a VPS or Linux server.


====================================================================
FILES
====================================================================

* times_to_epub_thin_v2.py
Python script that logs in to The Times via Selenium (Chrome), collects article URLs from the current edition, fetches the full content, builds an HTML file, and converts it to an EPUB using Calibre.

* run_times_epub_v3.sh
Shell wrapper that runs the Python script inside a virtual environment, cleans up old dumps, and handles environment variables (TIMES_USER, TIMES_PASS, GMX_PASS). It also sends the generated EPUB to Kindle via calibre-smtp.

* times_daily_runner.sh
A scheduler script (cron-free loop) that ensures the pipeline runs once per day at a fixed time (default: 22:00 CET). Includes retry logic (up to 3 attempts) and can send a warning email if all retries fail.

* README.txt
This documentation file.

* setup_pelle.sh
Bootstrap/setup script for a new VPS or environment. Installs system dependencies (Python, Chrome/Chromedriver, Calibre), creates the ~/venvs/times virtual environment, upgrades pip, and installs required Python libraries (selenium, webdriver-manager, beautifulsoup4, readability-lxml, python-dotenv, etc.). This script is intended to be run once when provisioning a new server.

====================================================================
REQUIREMENTS
====================================================================

* Linux (tested on Ubuntu VPS)

* Python 3.10+ with virtualenv

* Google Chrome + Chromedriver

* Calibre (ebook-convert, calibre-smtp)

* A subscription to The Times (UK)


====================================================================
 SOME USEFUL COMMANDS 
====================================================================
ssh root@95.111.204.220 # Log in to my Virtual Private Server from my laptop
sudo /root/setup_pelle.sh # Does several setups like virtual Python environment, and changes user to pelle_user
/home/pelle_user/times_daily_runner_v2.sh # Starts the scheduler script (Please do not use "sudo")

tail -f ~/times_runner.log # See the log 'live'
~/kill_all_v2.sh # kills all running processes, if needed
