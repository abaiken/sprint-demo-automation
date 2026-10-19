# Sprint Demo Automation

Local Python tooling for the sprint demo ceremonies coordinator workflow.

This project copies the latest sprint demo deck, updates the next demo date, rotates presenter order, keeps skipped team slides out of the active rotation, clears slide content that should be refilled, and prints a coordinator TODO list with the follow-up messages that still need a human.

## What It Does

- Finds the next sprint demo date from Google Calendar
- Finds the source presentation from a Google Drive folder or explicit Slides URL
- Copies the deck into Drive
- Updates the cover date range
- Rotates the presenter order for the next sprint by moving the last active team to the front
- Detects skipped team title slides and moves those teams to the end without including them in the active rotation
- Clears demo-slide content while preserving formatting
- Clears walkout-slide person-specific content while preserving labels and styling
- Updates the anniversary slide with the upcoming anniversaries from the configured hire-dates source, when available
- Prints a coordinator TODO summary instead of raw JSON

## Coordinator Output

When you run `create-deck`, the tool now prints:

1. The work anniversary people to find photos for
2. The Slack reminder message for the team channel, with the new deck link
3. The most likely walkout-song candidate, plus a message you can send them
4. A message you can send to the MC group

If you do not have a hire-dates source configured, the tool still runs. In that case it skips:

- anniversary suggestions
- walkout candidate suggestions

Everything else still works.

Walkout candidate selection currently prefers:

1. Anyone whose `Walkout` column is blank
2. Within that group, people with no recorded prior walkout
3. Then the longest-tenured person by hire date
4. Then the oldest recorded `Last Walkout Date`

## Project Layout

- `src/sprint_demo_automation/cli.py` - command-line entrypoint
- `src/sprint_demo_automation/config.py` - config loading
- `src/sprint_demo_automation/google_auth.py` - Google OAuth helpers
- `src/sprint_demo_automation/calendar_client.py` - next-demo date lookup
- `src/sprint_demo_automation/drive_client.py` - source deck lookup
- `src/sprint_demo_automation/slides_client.py` - live deck copy and slide edits
- `src/sprint_demo_automation/planner.py` - coordinator planning logic
- `src/sprint_demo_automation/messages.py` - ready-to-send draft messages
- `src/sprint_demo_automation/csv_support.py` - CSV parsing helpers
- `config.example.toml` - safe example config
- `.env.example` - optional environment variable overrides

## Setup

```bash
cd /path/to/sprint-demo-automation
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

## Install As A Package

This project is already packaged as a Python CLI tool. People with access to the private GitHub repo can install it directly.

### Option 1: Install Into A Virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "git+https://github.com/abaiken/sprint-demo-automation.git"
```

### Option 2: Install As A CLI With `pipx`

If someone wants the `sprint-demo` command available without manually activating a virtualenv each time:

```bash
pipx install "git+https://github.com/abaiken/sprint-demo-automation.git"
```

After either install path, they can run:

```bash
sprint-demo create-deck
```

Notes:

- they must have access to the private GitHub repo
- they still need their own `.env` file with Google credentials and local paths
- they should keep the hire-dates CSV outside the repo and point to it by path

## Quick Start For A Teammate

1. Clone the repo somewhere local
2. Create and activate a virtualenv
3. Install the package with `pip install -e .`
4. Copy `.env.example` to `.env`
5. Set the values in `.env` for:
   - a Google OAuth desktop client JSON
   - a Google token path
   - the source Drive folder or source presentation
   - optionally a destination Drive folder
   - optionally either a local hire-dates CSV path outside the repo or a Google Sheets URL/ID
6. Run `sprint-demo create-deck`

## Google Setup

You need a Google OAuth desktop client JSON that can access:

- Google Calendar
- Google Drive
- Google Slides

Do not store live credentials or tokens in the repo.

### If You Need To Create A Google OAuth Client

1. Open Google Cloud Console and create a new project, or select an existing project for this tool.
2. Enable the APIs this tool needs:
   - Google Calendar API
   - Google Drive API
   - Google Slides API
3. Open the OAuth consent screen setup for the project.
4. Fill in the basic app details:
   - app name
   - user support email
   - developer contact email
5. Choose the appropriate user type:
   - use `Internal` if your organization allows it and the app is only for people in your Google Workspace organization
   - otherwise use `External`
6. Add the scopes your app needs when prompted during consent screen setup.
7. If the app is still in testing mode and you used `External`, add yourself and any teammate testers as test users.
8. Open `Google Auth Platform > Clients`.
9. Create a new OAuth client with application type `Desktop app`.
10. Download the client JSON and store it outside this repo.

This project uses a desktop OAuth flow, so the credential type should be `Desktop app`, not `Web application` or `Service account`.

Recommended setup:

1. Keep your Google OAuth client file somewhere outside this project
2. Point the project at it in `.env`
3. Let the tool create the token file locally on first run
4. Keep that token file outside the repo too if you prefer

Example `.env` values:

```bash
SPRINT_DEMO_GOOGLE_CREDENTIALS_PATH=/absolute/path/to/credentials.json
SPRINT_DEMO_GOOGLE_TOKEN_PATH=/absolute/path/to/google_token.json
```

On the first calendar-backed or Slides-backed run, a browser window opens for consent and stores a token locally.

## Environment Variables

Edit `.env` and set:

- `SPRINT_DEMO_NEXT_DEMO_EVENT_TITLE`
- `SPRINT_DEMO_SOURCE_DRIVE_FOLDER_URL` or `SPRINT_DEMO_SOURCE_PRESENTATION_URL`
- optional `SPRINT_DEMO_DESTINATION_DRIVE_FOLDER_URL`
- optional `SPRINT_DEMO_DEFAULT_HIRE_DATES_CSV`
- optional `SPRINT_DEMO_HIRE_DATES_SHEET_URL` or `SPRINT_DEMO_HIRE_DATES_SHEET_ID`
- optional `SPRINT_DEMO_HIRE_DATES_SHEET_RANGE`
- `SPRINT_DEMO_GOOGLE_CREDENTIALS_PATH`
- `SPRINT_DEMO_GOOGLE_TOKEN_PATH`

Notes:

- the hire-dates source is optional
- if you use `SPRINT_DEMO_DEFAULT_HIRE_DATES_CSV`, it should be an absolute path to a CSV outside this repo
- if you use Google Sheets, set `SPRINT_DEMO_HIRE_DATES_SHEET_URL` or `SPRINT_DEMO_HIRE_DATES_SHEET_ID`
- `SPRINT_DEMO_HIRE_DATES_SHEET_RANGE` is optional; if omitted, the tool reads the first worksheet
- do not copy the hire-dates export into this project directory
- if the configured title does not match exactly, the tool still tries to find the next likely sprint-demo event
- the tool accepts normal Google Drive and Google Slides URLs, not just raw IDs

Example local-only values:

```bash
SPRINT_DEMO_NEXT_DEMO_EVENT_TITLE="Sprint Demo"
SPRINT_DEMO_SOURCE_DRIVE_FOLDER_URL="https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
SPRINT_DEMO_DESTINATION_DRIVE_FOLDER_URL="https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
SPRINT_DEMO_GOOGLE_CREDENTIALS_PATH="/absolute/path/to/credentials.json"
SPRINT_DEMO_GOOGLE_TOKEN_PATH="/absolute/path/to/google_token.json"
SPRINT_DEMO_DEFAULT_HIRE_DATES_CSV="/absolute/path/to/hire-dates.csv"
# OR use a Google Sheet instead of a local CSV
SPRINT_DEMO_HIRE_DATES_SHEET_URL="https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit"
SPRINT_DEMO_HIRE_DATES_SHEET_RANGE="Hire dates!A:Z"
```

## Optional TOML Config

If someone prefers a local config file instead of `.env`, they can still copy `config.example.toml` to `config.toml` and use that. `.env` is the recommended setup path for teammates.

## Ceremony Coordinator Setup

A ceremonies coordinator only needs to do these things:

1. Install Python dependencies
2. Create a local `.env`
3. Point the tool at a Google OAuth client file
4. Optionally set a hire-dates source, either a local CSV path or a Google Sheet
5. Run `create-deck`

If they skip the hire-dates source, they will still get:

- the copied deck
- the deck link
- the team-channel reminder message
- the MC request message

They just will not get:

- anniversary-photo TODOs
- walkout-candidate suggestions

A local CSV is intentionally optional because we do not want hire-date data committed to the repo. If you use a Google Sheet instead, the tool reads it directly and avoids a local copy altogether.

## Usage

### Show the next demo date

```bash
sprint-demo next-demo-date
```

### Resolve the source deck from a Drive folder

```bash
sprint-demo resolve-source-deck --folder-id "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
```

### Create the next deck from the latest presentation in a Drive folder

```bash
sprint-demo create-deck --folder-id "https://drive.google.com/drive/folders/YOUR_FOLDER_ID"
```

### Create the next deck from an explicit Slides URL

```bash
sprint-demo create-deck \
  --source-presentation-url "https://docs.google.com/presentation/d/FILE_ID/edit"
```

### Dry run from a hire-dates CSV

```bash
sprint-demo dry-run --hire-dates-csv "/absolute/path/to/hire-dates.csv"
```

### Preview the team-channel reminder

```bash
sprint-demo preview-lead-reminder \
  --deck-name "HCM Fleet Sprint Demo_100626" \
  --deck-url "https://docs.google.com/presentation/d/example/edit"
```

## Current Behavior

The deck copy flow currently does all of this:

- copies the source deck
- renames it based on the next demo date
- updates the cover date range
- rotates presenter order by moving the last active team to the front
- keeps skipped team title slides at the end and out of the active team rotation
- normalizes demo slides
- clears the walkout slide person-specific content
- keeps one anniversary slide and updates it when a local CSV is available
- clears most team-slide body content while preserving layout and headers

The team-slide cleanup is intentionally conservative right now. It preserves the overall design and obvious headers, but some slides may feel a little sparse. That is a safe baseline and can be refined team-by-team later.

## Remaining Gaps

- pull anniversary photos automatically
- build the walkout slide from form responses
- send Slack messages directly instead of printing drafts
- make team-slide cleanup smarter for known slide patterns

## Sensitive Data

This project now ignores:

- `.env`
- `config.toml`
- `credentials.json`
- `google_token.json`
- common local hire-date CSV filenames

Those files are local-only and should not be committed.

The intended workflow for hire-date data is one of these:

1. Preferred: point `SPRINT_DEMO_HIRE_DATES_SHEET_URL` or `SPRINT_DEMO_HIRE_DATES_SHEET_ID` at the live Google Sheet
2. Fallback: export the CSV somewhere outside this repo
3. If using CSV, point `default_hire_dates_csv` or `SPRINT_DEMO_DEFAULT_HIRE_DATES_CSV` at that file
4. Keep any local data file out of version control entirely
