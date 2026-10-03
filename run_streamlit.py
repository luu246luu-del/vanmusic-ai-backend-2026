"""Tiện ích: chạy Streamlit bằng  python run_streamlit.py  (tương đương  streamlit run streamlit_app/app.py)."""
import subprocess
import sys

raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", "streamlit_app/app.py"]))
