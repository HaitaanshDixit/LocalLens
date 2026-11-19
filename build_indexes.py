"""
Pre-build (or validate) the FAISS indexes without starting the server:

    python build_indexes.py

Useful before deploying, so the first server start loads from cache in seconds instead of spending minutes embedding every row.
"""
from dotenv import load_dotenv

load_dotenv()

from services.rag_service import get_status, load_all_rag_data

if __name__ == "__main__":
    load_all_rag_data()
    print(get_status())