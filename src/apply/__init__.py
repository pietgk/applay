"""Reusable application-pipeline logic behind the command-line tools.

Submodules are intentionally imported by callers rather than eagerly here.
That keeps lightweight commands such as job discovery and draft initialization
independent of WeasyPrint's native rendering libraries.
"""
