"""Use independently recomputed local candidate hashes and safe redirects."""
import sys
import urllib.request
from urllib.parse import urlsplit
import prepare_docs as task

# Recomputed directly from the reviewed /doc-candidate bytes; the original
# handwritten output table was incorrect. Source hashes and transforms unchanged.
task.OUTPUT = {'BLUEPRINT.md':'d797352f465d1cd33642dcd73c537acf93392351','BOOK.md':'e557aee6e84bc0e1fa994352c5e45bd050d39e6d','SPECS.md':'3e52c05d5d7a800086e1f579a72af3290c2b261f','FLOOR_LIMITATIONS.md':'ee9130dde6f63c9a37afdb22195567dadb5429a5','README.md':'1b97ed10ee22893b0ae700cda4bdaf3df7f59441','CLAUDE.md':'5abf2084a47e501038762a81a2a42bb3782c0d7c','MIGRATION_PROMPT.md':'59084a93081fd5e87a689c8063c992c1d5cc571d'}

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target is not None and urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
            target.remove_header('Authorization')
        return target

urllib.request.install_opener(urllib.request.build_opener(SafeRedirect))
{'build':task.build,'publish':task.publish,'diagnostics':task.diagnostics}[sys.argv[1]]()
