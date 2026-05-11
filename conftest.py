"""Root conftest — registers the --live flag and auto-skips live tests."""
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live BLE hardware tests (requires the physical UT353BT meter).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--live"):
        return  # Run everything — user opted in

    skip_live = pytest.mark.skip(
        reason="Live BLE test skipped — run with: pytest -m live --live"
    )
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip_live)
