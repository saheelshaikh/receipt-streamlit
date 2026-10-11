# Receipt register — Streamlit Community Cloud

Free-hosting edition with an editable Date / Receipt number / Amount table,
original scan preview, and Excel and PDF downloads. Each browser session has
its own batch. Sessions are temporary: download results before leaving.

## Deploy

1. Create a new private GitHub repository named `receipt-streamlit`.
2. Extract `Receipt-Streamlit.zip`. Upload all files inside the extracted folder
   to the repository root, then commit. `streamlit_app.py`, `requirements.txt`,
   and `packages.txt` must appear on the main file list.
3. Sign in at https://share.streamlit.io with GitHub. Allow access to this repo.
4. Click Create app, then Yup, I have an app. Select the repo, branch `main`, and
   main file `streamlit_app.py`.
5. Under Advanced settings select Python **3.12**. In Secrets enter:

```toml
APP_PASSWORD = "REPLACE_WITH_YOUR_OWN_PASSWORD"
```

Replace the example value with your own unique password of 16–256 characters.
Do not put the real password in GitHub. No SECRET_KEY or Dockerfile is needed.
6. Save and deploy. Check app sharing settings to allow intended viewers;
   private apps can require inviting viewers through Streamlit in addition
   to entering the app's team password.
7. Try 1–3 pages, review blanks and all extracted values, edit a cell, click
   Prepare downloads, then download both formats. Live cloud OCR remains to be
   verified after deployment. This package does not create a hosted app by itself.

The receipt parser is tuned to the provided Aldrees sample. Other formats can
require manual entry. Limits: 20 MB and 30 PDF pages per upload. Files are
processed in temporary directories; only the current session retains previews
and results. Original receipts must not be committed to GitHub.

Official instructions: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

Local run: install requirements using Python 3.12, configure APP_PASSWORD in
`.streamlit/secrets.toml` (ignored by Git), then run `streamlit run streamlit_app.py`.

Local validation: sample receipt OCR, sign-in gating, wrong-password handling,
editor rendering, blank amount preservation, both exports, separate sessions,
and sign-out cleanup passed. Cloud deployment is not yet performed.
