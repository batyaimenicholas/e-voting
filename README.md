# VoteSafe – Online Voting System

A complete, ready-to-run voting system for any group (association, club, union, church board, SACCO, alumni body).
Positions come pre-filled: **President, Vice President, Deputy, Speaker, Secretary, Treasurer, Publicity Secretary**.
You can add, remove or rename positions and candidates.

## What it does
| Feature | How it works |
|---|---|
| Voter login | **Full name + email + phone number** must all match the voter list |
| One vote only | The voter is locked as "voted" in the same step the ballot is saved |
| Secret ballot | Votes are stored without the voter's identity |
| Easy voting | One position per screen, progress bar, review page, final confirmation, receipt number |
| Admin panel | Open/close voting, manage candidates and voters, import voters, live results, CSV export |
| Results | Hidden from voters until the admin closes voting |

## Requirements
Only **Python 3.8 or newer**. Nothing else to install. Works on Windows, Linux and macOS.

## Run it (2 minutes)
1. Unzip the folder.
2. **Windows:** double-click `start.bat`. **Linux/Mac:** run `./start.sh`.
3. Open **http://localhost:8000** (voters) and **http://localhost:8000/#admin** (administrator).
4. Admin password on first run: **Admin@123** – change it straight away (Admin → Settings).

Sample data is included (7 positions, 5 voters such as alice@example.com / Alice Namukasa / 0772000001).
When ready for the real election: Admin → Settings → **Clear all data**, then add your own.

## Let other people vote (same network or internet)
* **Same Wi-Fi/office network:** find the computer's IP (e.g. 192.168.1.20). Voters open `http://192.168.1.20:8000`. Allow port 8000 in the firewall.
* **Internet:** run it on a small cloud server (any Linux VPS) and put it behind HTTPS (Caddy or Nginx with a free Let's Encrypt certificate). **Always use HTTPS for real elections.**
* Change port: `PORT=9000 python3 server.py`. Change database location: `VOTE_DB=/path/voting.db`.
* Keep running on Linux: create a systemd service that runs `python3 /opt/votesafe/server.py`.

## Backup
Everything lives in `data/voting.db`. Copy this one file to back up. Do it before opening, after closing, and once during voting.

## Folder contents
`server.py` (system) · `static/index.html` (screens) · `data/` (database) · `docs/` (guides) · `sample_voters.csv`
