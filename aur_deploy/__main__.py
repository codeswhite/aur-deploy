from pathlib import Path

from aur_deploy.aur_deploy import aur_deploy

if __name__ == "__main__":
    aur_deploy(Path.cwd())
