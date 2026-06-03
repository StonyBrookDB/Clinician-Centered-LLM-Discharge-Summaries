"""Install or reset the demo-only dummy account."""

from __future__ import annotations

from eval_v2.services.dummy_account import install_dummy_account


def main() -> None:
    install_dummy_account()


if __name__ == "__main__":
    main()
