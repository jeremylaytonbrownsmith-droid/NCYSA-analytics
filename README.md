# NCYSA Find My Club — analytics refresh

Automated pull of the Find My Club GA4 data that feeds the board report.

## Phase A (now): reconciliation only. Publishes nothing.

`ga_pull.py` reads the GA4 property with the read-only service account and
prints a table comparing live numbers to the July baseline. This proves the
API access and the numbers before we ever touch the live page.

### One-time setup
1. In the repo: **Settings → Secrets and variables → Actions → New repository secret.**
   - Name: `GA4_SA_KEY`
   - Value: paste the **entire contents** of the service-account JSON key file.
2. Commit these files to the repo (`ga_pull.py`, `requirements.txt`,
   `.github/workflows/refresh.yml`, this README).

### Run it
- Go to the **Actions** tab → **NCYSA Find My Club refresh** → **Run workflow.**
- Leave the end date at `2026-07-20` to compare against the July baseline.
- Open the run’s log to see the reconciliation table, and download the
  `ga_results.json` artifact for the raw numbers.

The Property ID (`514757424`) is set in the workflow, not in the secret.

## Phase B (next, after the numbers check out)
- Turn `ga_results.json` into the rebuilt `.fmcr-` board-report HTML
  (needs the current page HTML as the template).
- Add a WordPress publish step (application password) that pushes to a draft
  and notifies, then to live once confirmed.
- Uncomment the `schedule:` block in the workflow for hands-off refreshes.

Nothing in Phase A writes anywhere. It is safe to run as often as you like.
