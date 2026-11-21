# Live demo checklist

1. Configure the four Bodhan model keys and a general LLM provider in `.env`. Run the [demo commands](README.md#demonstrations) from the recipe directory with hosted credit available. Use distinct output folders and retain the cold-run reports before resuming.
2. Confirm `report.json` shows 20 NCERT pages and 12 Malayalam pages; note any omissions, wall time and estimated INR. Confirm language detection returns `ml` for the Malayalam chapter, or record why a source hint was needed.
3. Inspect page coverage, removed footers, figure captions, exact LaTeX and tables. Check each target's translated sections, CER and loudness. Listen to a section and use an MP3 player or `ffprobe -show_chapters` to verify navigation. Ask native speakers to review a passage where available.
4. Record ≤5 minutes: (0:00–0:30) show the commands and a scan; (0:30–1:30) display the full run using time-lapse; (1:30–2:30) show source and translated structure; (2:30–3:40) play a short AI-generated section and jump to a chapter; (3:40–4:40) show the Malayalam run and QA, cost and runtime. Keep secrets and private material off screen.
5. Add reviewer-accessible links to the live reports, permissible output samples and video in the README and PR. Keep the textbooks and full derived content out of the repo; share only material you are allowed to redistribute. Check access from a signed-out session.
6. Run `make check` from the Cookbook root and the recipe tests from this folder. Open the PR with the [draft](PR_DESCRIPTION.md); submit its URL and final commit SHA on the assignment email thread.

Current status: the two-page hosted smoke test produced verified full MP3s for Hindi, Tamil and Bengali. The full textbook walkthrough requires additional hosted Indic-Speak capacity. For the chapter runs, record the provider model, elapsed time, per-language coverage, section CER and LUFS, page costs and unresolved warnings.
