# FED Funds 2026 dashboard

An executive dashboard of the FY 2026 maintenance and operations funds for DPWH floating equipment.
Every morning GitHub reads the **Regular-FY2026** tab of the FED FUNDS 2026 Google Sheet, rebuilds
`docs/index.html`, and publishes it as a web page.

> **Think of it like a newspaper printing press.** The Google Sheet is the reporters' notes.
> At 6:45 AM the press (GitHub Actions) wakes up, reads the notes, prints a fresh front page
> (`docs/index.html`) and puts it on the newsstand (GitHub Pages) before 7:00 AM.
> Nobody has to press anything.

---

## What's in this folder

| File | What it does |
|---|---|
| `template.html` | The look of the dashboard (layout, colors, charts, filters). |
| `build_dashboard.py` | Downloads the sheet, cleans the rows, puts the numbers into the template. |
| `.github/workflows/update-dashboard.yml` | The alarm clock: runs the build every day at 6:45 AM (PH time). |
| `docs/index.html` | The finished dashboard. This is the page people open. |

---

## One-time setup (about 15 minutes)

### Step 1 — Create the repository
1. Sign in at <https://github.com> (create a free account if you don't have one).
2. Click **+** (top right) → **New repository**.
3. Repository name: `fed-funds-dashboard`. Choose **Public**. Leave everything else unticked.
4. Click **Create repository**.

### Step 2 — Upload the files
1. On the new, empty repository page, click the link **uploading an existing file**.
2. Unzip `fed-funds-dashboard.zip` on your computer, open the folder, select **everything inside it**
   and drag it into the GitHub page.
3. Scroll down and click **Commit changes**.

> **Hidden folder warning.** The `.github` folder starts with a dot, so Windows and Mac may hide it
> and it won't get uploaded. After uploading, check that you can see a `.github` folder in the
> repository. If it's missing:
> click **Add file → Create new file**, type the name
> `.github/workflows/update-dashboard.yml` (the slashes create the folders),
> paste the contents of that file from the zip (open it with Notepad / TextEdit), then **Commit changes**.

### Step 3 — Tell GitHub where the sheet is (kept secret)
1. In the repository, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `SHEET_ID`
4. Secret: the long code in your Google Sheet link, between `/d/` and `/edit`.
   Example: in `https://docs.google.com/spreadsheets/d/ABC123xyz/edit`, the ID is `ABC123xyz`.
5. Click **Add secret**.

Why a secret? The repository is public. A secret is like a sealed envelope: GitHub can open it
while it builds the page, but visitors can never see it, so the sheet link (and its internal
remarks) stays private.

### Step 4 — Let the robot save its work
1. **Settings → Actions → General**.
2. Scroll to **Workflow permissions**, choose **Read and write permissions**, click **Save**.

### Step 5 — Run it once by hand
1. Open the **Actions** tab. If GitHub asks, click **I understand my workflows, go ahead and enable them**.
2. Click **Update dashboard** on the left → **Run workflow** → **Run workflow**.
3. Wait about 1 minute for a green check mark ✓.

### Step 6 — Publish the page
1. **Settings → Pages**.
2. Under **Build and deployment**, Source: **Deploy from a branch**.
3. Branch: **main**, folder: **/docs** → **Save**.
4. After 1–2 minutes the page is live at
   `https://YOUR-GITHUB-USERNAME.github.io/fed-funds-dashboard/`

That's the link to send to executives. It works on phones too.

---

## Everyday use

- **You don't need to do anything.** Keep encoding in the Google Sheet as usual; the page refreshes by 7:00 AM daily.
- **Need it refreshed right now?** Actions → Update dashboard → Run workflow.
- **Share a filtered view.** Pick filters on the page (e.g. *OKB only* + *Region XI*) and copy the browser
  address; the link opens with the same filters.
- **Export.** The *Export CSV* button downloads the requests currently shown in the table.

### Rules the dashboard follows (so the sheet must keep them)

| The dashboard needs… | So please… |
|---|---|
| The header row that starts with `FED Release Date:` | Keep the column names as they are (order can change). |
| One reference number like `FED-SAAreg2026-001` per request in **File Link:** | Keep using that numbering. Rows without one are ignored. |
| The `TOTAL ALLOTMENT:` and `REMAINING BALANCE FOR 2026:` rows under the list | Keep notes and scratch rows **below** those two rows. |
| `Oplan Kontra Baha` or `OKB` in **Remarks** | Type one of these in Remarks to tag a request as OKB. |
| Sharing set to *Anyone with the link* | Keep it on. *Viewer* is enough (safer than *Commenter*). |

### How requests are grouped

| Request type on the dashboard | Fund Type in the sheet |
|---|---|
| Dredging by administration | contains Operational, Labor, OSH, Bunkhouse or Office Supplies |
| Preventive maintenance | Preventive Maintenance |
| Corrective maintenance | Corrective Maintenance |
| Dry docking and repair | Dry Docking and Repair (including *Supplemental*) |
| Accessories | Accessories |
| Mobilization | Mobilization (alone) |
| Other | anything else, e.g. Spoils Management, Shop Tools |

Statuses come straight from the **Status** column: *approved. for SAA*, *released from BOE*,
*released from FED*, *for signature of Section Chiefs*, or blank (*No status yet*).
To change any rule, edit `classify_request` or `classify_status` in `build_dashboard.py`.

### Totals
- **Sub-allotted** = sum of the Allotment column. The page checks this against the sheet's
  `TOTAL ALLOTMENT:` cell and shows a warning if they differ.
- **Remaining** = Total allotment − Sub-allotted (same as the Status of Funding report).
  The ₱47,083,496.00 administrative overhead is shown as a note, not subtracted.

---

## Troubleshooting

| What you see | What to do |
|---|---|
| Red ✗ in the Actions tab | Click the run. The **Annotations** box gives the reason in plain words (e.g. *The SHEET_ID secret is missing*, *Google did not share the sheet*, *A column was renamed*) and what to do. The page keeps showing the last good version. |
| Yellow *Node.js 20 is deprecated* or blue *ubuntu-latest will migrate* notes | Information only from GitHub. They don't stop the build. |
| *Files are in the wrong place* | `build_dashboard.py` and `template.html` must sit at the top level, next to `README.md` and `.github`, not inside a `fed-funds-dashboard` folder. |
| *Sheet or tab not found* after re-creating a tab | Open the tab in Google Sheets, copy the number after `#gid=` in the address bar, and save it under Settings → Secrets and variables → Actions → **Variables** as `REGISTER_GID` (Regular-FY2026 tab) or `SOF_GID` (Status of Funding tab). |
| The page says *Not refreshed for 1 day* | The daily run failed or was skipped; check the Actions tab and run it by hand. |
| Updated at 7:10 instead of 7:00 | GitHub sometimes starts scheduled runs late on busy mornings. To start earlier, change `45 22` in the workflow file (that's UTC: 22:45 UTC = 6:45 AM PH). |
| Email: *scheduled workflow disabled* | GitHub pauses schedules on repositories with no activity for 60 days. Open Actions → Update dashboard → **Enable workflow**. (The daily update normally counts as activity, so this is rare.) |
| A filter is missing a region or type | It appears automatically once the sheet has at least one request for it. |

## Privacy
- The page is public: anyone **with the link** can open it. It asks search engines not to list it.
- Internal Remarks text, sub-allotment numbers and file links are **not** published.
- The sheet ID is stored as a GitHub secret and never appears on the page or in this repository.

## Testing on your own computer (optional)
```
python build_dashboard.py --csv register.csv --sof-csv status.csv
```
Download the two tabs as CSV first (File → Download → CSV), then open `docs/index.html` in a browser.
