from flowback.common.tests import fake


def pytest_runtest_setup():
    fake.unique.clear()
