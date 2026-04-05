# Contributing to MiBud

Thank you for your interest in contributing to MiBud! 🎉

## Getting Started

1. **Fork** the repository and clone your fork locally.
2. Create a **feature branch**: `git checkout -b feature/my-feature`
3. Make your changes, following the guidelines below.
4. **Test** your changes: `pytest tests/ -v`
5. **Lint** your code: `ruff check .`
6. **Commit** with a clear message: `git commit -m "feat: add X"`
7. **Push** to your fork and open a **Pull Request**.

## Development Setup

```bash
git clone https://github.com/NaustudentX18/MiBud.git
cd MiBud
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in any API keys you want to test with
```

> **Note:** Pi-specific packages (`RPi.GPIO`, `spidev`, `picamera2`, etc.) are excluded
> on non-Pi platforms. The app uses mock hardware drivers automatically when not running
> on a Raspberry Pi.

## Code Style

- Python 3.10+
- Format with `ruff` (already configured in the project)
- Keep functions small and focused
- Add docstrings to public classes and methods
- Prefer explicit imports over wildcard imports

## Areas Welcoming Contributions

- Additional AI provider integrations
- New personality presets
- UI/UX improvements to the web dashboard
- Hardware driver improvements
- Documentation and translations
- Bug fixes and test coverage

## Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template.
Include hardware details (Pi model, HAT version) when relevant.

## Proposing Features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template.

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing you agree that your contributions will be licensed under the
[MIT License](LICENSE).
