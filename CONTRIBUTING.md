# Contributing

Open an issue describing the account workflow or failure first. Include macOS and official-client versions and a redacted error. Never attach credentials, private transcripts or a full account directory.

Use `uv run python -m unittest discover -s tests -v` for backend checks and `uv run python install.py --package build/SessionPier-test.zip` for a native build. Keep fixtures synthetic. Account isolation, process targeting, truthful freshness and preservation of existing work are required behavior.

UI changes should be checked in the real native app, including the menu panel, main window, settings, empty states and keyboard access. Record what was actually observed. Test notification or sign-in changes with accounts you control. Do not send model messages just to test usage polling.
