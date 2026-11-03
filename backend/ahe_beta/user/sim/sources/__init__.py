"""SeedSource implementation subpackage (spec-0009/T1).

`seed_source._discover()` traverses this package during import and imports each module in turn, triggering
self-registration via each module's `@register` decorator. Adding a source therefore means adding a module
here, no registry changes needed (spec-0009/T2's empty source is an example).
"""
