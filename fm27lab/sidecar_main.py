from fm27lab.config import Settings
from fm27lab.sidecar import run


def main() -> None:
    raise SystemExit(run(Settings.from_env()))


if __name__ == "__main__":
    main()
