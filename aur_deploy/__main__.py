from aur_deploy.aur_deploy import aur_deploy


def parse_args():
    from argparse import ArgumentParser
    parser = ArgumentParser()

    parser.add_argument('-f', '--force', action='store_true',
                        help='Dont check remote version, attempt to deploy anyway')

    return parser.parse_args()


def main():
    aur_deploy(parse_args())


if __name__ == "__main__":
    main()
