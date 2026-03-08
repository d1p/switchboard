"""Entry point for the switchboard command."""
from .app import SwitchboardApp


def main() -> None:
    app = SwitchboardApp()
    app.run()


if __name__ == "__main__":
    main()
