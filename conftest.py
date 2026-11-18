from flowback.common.tests import fake

from backend.settings import INTEGRATIONS

# Optional addons can only be imported while they are installed
collect_ignore = []
if 'flowback_addon.flowback_ledger_module' not in INTEGRATIONS:
    collect_ignore.append('flowback_addon')


def pytest_runtest_setup():
    fake.unique.clear()
