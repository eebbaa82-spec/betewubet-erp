import pytest

from apps.catalog import demo_data


@pytest.fixture
def demo(db):
    demo_data.load()
    demo_data.load_stock()
