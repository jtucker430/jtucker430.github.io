"""
Shared configuration for all update scripts.
"""

import os

# --- Paths ---
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PUBLICATIONS_YAML = os.path.join(REPO_ROOT, "_data", "publications.yml")
SITE_CONTENT_YAML = os.path.join(REPO_ROOT, "_data", "site_content.yml")
COMMENTARY_DIR = os.path.join(REPO_ROOT, "_commentary")
CV_PDF = os.path.join(REPO_ROOT, "assets", "Tucker_CV.pdf")

# --- Google Scholar ---
SCHOLAR_AUTHOR_ID = "fc0VgPAAAAAJ"

# --- CSMAP ---
CSMAP_BASE_URL = "https://csmapnyu.org"

# --- Author name variants for matching ---
AUTHOR_NAME_VARIANTS = [
    "Joshua Tucker",
    "Joshua A. Tucker",
    "J.A. Tucker",
    "J. Tucker",
    "Tucker, Joshua",
    "Tucker, Joshua A.",
    "Tucker, J.A.",
    "Tucker, J.",
]
