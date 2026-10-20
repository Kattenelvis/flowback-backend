from django.urls import path, include

from .flowback_ledger_module.urls import ledger_patterns

# Mounted by the backend (backend/urls.py) when INTEGRATIONS is set
addon_patterns = [
    path('ledger/', include((ledger_patterns, 'ledger'))),
]
