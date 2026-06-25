# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# Project information
project = "bleak-smlight"
copyright = "2026, Bluetooth Devices Authors"
author = "Bluetooth Devices Authors"
release = "1.0.0"

# General configuration
extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
]

# autodoc: keep signatures readable and respect source order.
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# Cross-reference the Python stdlib for types used in signatures.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# The suffix of source filenames.
source_suffix = [
    ".rst",
    ".md",
]
templates_path = [
    "_templates",
]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
]

# Options for HTML output
html_theme = "furo"
html_static_path = ["_static"]
