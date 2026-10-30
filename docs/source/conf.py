import json
import os
import sys

sys.path.insert(0, os.path.abspath('../../custom_components'))

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'cremalink-ha'
copyright = '2026, Midian Tekle Elfu'
author = 'Midian Tekle Elfu'
try:
    with open(os.path.abspath('../../custom_components/cremalink_ha/manifest.json'),
              encoding='utf-8') as f:
        version = json.load(f)['version']
except (OSError, KeyError, json.JSONDecodeError):
    version = '0.0.0'
release = version


# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.githubpages',
    'sphinx_rtd_theme'
]

# The integration's modules import Home Assistant at module level. CI
# installs the real framework (real imports always beat this list); the
# mocks keep bare-environments builds working — config_flow needs a real
# ConfigFlow base for its `domain=` class keyword, so its page is
# partial when homeassistant is only mocked.
autodoc_mock_imports = ['homeassistant', 'voluptuous']

intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}

exclude_patterns = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_logo = "icon.png"
html_theme_options = {
    'logo_only': True,
}
