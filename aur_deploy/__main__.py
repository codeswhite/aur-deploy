from aur_deploy.aur_deploy import aur_deploy
from pathlib import Path


def parse_args():
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument('-d', '--directory', type=str, default=Path.cwd(),
                        help='Specify working directory')
    parser.add_argument('--aur-depends', nargs='+', dest='aur_depends',
                        help='Pass which dependencies we should add to PKGBUILD')
    parser.add_argument('--no-aur', action='store_true',
                        help='Dont interact with PKGBUILD, only PyPI')
    parser.add_argument('-f', '--force', action='store_true',
                        help='Dont check remote version, attempt to deploy anyway')
    return parser.parse_args()


def main():
    exit(aur_deploy(parse_args()))


if __name__ == "__main__":
    main()
