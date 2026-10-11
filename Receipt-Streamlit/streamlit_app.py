"""Receipt review app for Streamlit Community Cloud. No persistent uploads."""
import hashlib
import hmac
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import streamlit as st
from receipt_core import KEYS, extract, validate_rows, export_xlsx, export_pdf
from runtime_state import OCR_LOCK, LOGIN_LOCK, FAILURES

st.set_page_config(page_title='Receipt register', layout='wide')
st.title('Receipt register')
try:
    password = str(st.secrets.get('APP_PASSWORD', ''))
except FileNotFoundError:
    password = ''
if not 16 <= len(password) <= 256:
    st.error('Setup needed: add APP_PASSWORD (16–256 characters) in the app Secrets settings.')
    st.stop()
fingerprint = hashlib.sha256(password.encode()).hexdigest()
if st.session_state.get('auth') != fingerprint:
    # Remove data when a session expires or the team password changes.
    for name in list(st.session_state):
        if name in {'auth', 'rows', 'previews', 'generation', 'exports'} or name.startswith(('editor_', 'page_')):
            del st.session_state[name]
    with st.form('login'):
        entered = st.text_input('Team password', type='password', key='login_password')
        submitted = st.form_submit_button('Sign in')
    if submitted:
        with LOGIN_LOCK:
            now = time.monotonic()
            while FAILURES and FAILURES[0] < now - 600: FAILURES.popleft()
            if len(FAILURES) >= 20:
                st.error('Too many attempts. Try again in 10 minutes.')
            elif hmac.compare_digest(entered.encode(), password.encode()):
                st.session_state.auth = fingerprint
                del st.session_state['login_password']
                st.rerun()
            else:
                FAILURES.append(now)
                st.error('Incorrect password.')
    st.stop()

if st.button('Sign out and clear my batch'):
    st.session_state.clear()
    st.rerun()
st.warning('Temporary session: download your Excel or PDF before closing or refreshing this page. Keep your original scans.')
st.caption('Your batch belongs to this browser session. Other users have separate batches. Uncertain values stay blank.')
upload = st.file_uploader('Upload a receipt PDF or image (up to 20 MB / 30 PDF pages)', type=['pdf','png','jpg','jpeg'])
if st.button('Extract receipts', disabled=upload is None):
    if upload.size > 20_000_000:
        st.error('Choose a file smaller than 20 MB.')
    elif not OCR_LOCK.acquire(blocking=False):
        st.info('Another scan is processing. Please try again shortly.')
    else:
        try:
            with st.spinner('Reading receipts…'), TemporaryDirectory(prefix='receipts-') as temp:
                folder = Path(temp)
                source = folder / ('source' + Path(upload.name).suffix.lower())
                source.write_bytes(upload.getvalue())
                rows = extract(source, folder)
                previews = [(folder / row['image']).read_bytes() for row in rows]
            st.session_state.rows = rows
            st.session_state.previews = previews
            st.session_state.generation = st.session_state.get('generation', 0) + 1
            st.session_state.pop('exports', None)
        except Exception:
            st.error('Could not process this file. Use an unencrypted PDF of up to 30 pages or a clear image. Try 1–3 pages first.')
        finally:
            OCR_LOCK.release()

if 'rows' not in st.session_state:
    st.stop()
rows = st.session_state.rows
generation = st.session_state.generation
left, right = st.columns([3, 2])
with left:
    st.subheader('Review and edit')
    st.caption('Dates: YYYY-MM-DD. Receipt numbers are text, preserving leading zeros. Press Enter to finish a cell edit.')
    edited = st.data_editor(
        [{key: row[key] for key in KEYS} for row in rows],
        key=f'editor_{generation}', hide_index=True, num_rows='fixed',
        column_config={
            'date': st.column_config.TextColumn('Date'),
            'receipt_number': st.column_config.TextColumn('Receipt number'),
            'amount': st.column_config.TextColumn('Amount (SAR)'),
        }, width='stretch',
    )
with right:
    page = st.selectbox('Original receipt', range(len(rows)), format_func=lambda i: f'Page {i+1}', key=f'page_{generation}')
    st.image(st.session_state.previews[page], width='stretch')
    if rows[page]['reasons']:
        st.caption('Original extraction: ' + '; '.join(rows[page]['reasons']))

signature = json.dumps(edited, sort_keys=True)
if st.button('Prepare downloads from these edits'):
    try:
        clean = validate_rows([{k: row.get(k) or '' for k in KEYS} for row in edited])
        with TemporaryDirectory(prefix='receipt-export-') as temp:
            xlsx, pdf = Path(temp)/'receipts.xlsx', Path(temp)/'receipts.pdf'
            export_xlsx(clean, xlsx)
            export_pdf(clean, pdf)
            st.session_state.exports = (signature, xlsx.read_bytes(), pdf.read_bytes())
    except ValueError as error:
        st.error(str(error))
    except Exception:
        st.error('Download preparation failed. Please try again.')
exports = st.session_state.get('exports')
if exports and exports[0] == signature:
    st.download_button('Download Excel', exports[1], 'receipts.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    st.download_button('Download PDF', exports[2], 'receipts.pdf', 'application/pdf')
elif exports:
    st.info('Your edits changed. Click Prepare downloads again to include them.')
