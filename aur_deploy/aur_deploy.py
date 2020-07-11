from shutil import rmtree
from os import rename
import subprocess
from pathlib import Path
from hashlib import sha256
from packaging import version
from fileinput import FileInput

from interutils import pr, pause
from requests import get
from bs4 import BeautifulSoup


def read_twine_token():
    return Path(__file__).parent.parent.joinpath(
        'data', 'twine_token').read_text().strip()


def get_pypi_ver(name):
    pr('Checking PyPI: ', end='')
    url = f'https://pypi.org/project/{name}/'
    res = get(url)
    if res.status_code != 200:
        print('Not found!')
        return '0'
    bs = BeautifulSoup(res.text, features='html.parser')
    h1 = bs.find('h1', {"class": 'package-header__name'})
    ver = h1.get_text(strip=True).split()[-1]  # Version
    print(ver)
    return ver


def get_aur_ver(name):
    pr('Checking AUR: ', end='')
    url = f'https://aur.archlinux.org/packages/python-{name}/'
    res = get(url)
    if res.status_code != 200:
        print('Not found!')
        return '0'
    bs = BeautifulSoup(res.text, features='html.parser')
    d = bs.find('div', {"id": 'pkgdetails'})
    h2 = d.find('h2')
    ver = h2.get_text(strip=True).split()[-1]  # Version
    print(ver)
    return ver


def aur_deploy(args, directory=Path.cwd()):
    if not directory.joinpath('setup.py').is_file():
        return pr('No setup.py found in current directory!', 'X')

    # Load setup.py
    title, new_ver, description = subprocess.check_output(
        ['python3', 'setup.py', '--name', '--version', '--description'],
        cwd=directory).decode().splitlines()
    pr(f'Project {title} {new_ver} in: {directory}')

    # Check PyPI
    if args.force or version.parse(new_ver) > version.parse(get_pypi_ver(title)):
        if not pause('publish to PyPI', cancel=True):
            return

        # Clean build and dist
        for f in directory.iterdir():
            if f.name in ('build', 'dist'):
                pr(f'Removing: {f}')
                rmtree(f)

        # Build wheel
        pr('Building wheel')
        if 0 != subprocess.call(
            ['python3', './setup.py', 'sdist', 'bdist_wheel'],
                cwd=directory, stdout=subprocess.DEVNULL):
            return pr('Bad exit code from setup bulid wheel!', 'X')

        # Check via twine
        pr('Checking via twine')
        if 0 != subprocess.call(
            ['python3', '-m', 'twine', 'check', './dist/*'],
                cwd=directory):
            return pr('Bad exit code from twine check!', 'X')

        # Publish via twine
        pr('Publishing via twine')
        if 0 != subprocess.call(
            ['python3', '-m', 'twine', 'upload', './dist/*'],
            env={'TWINE_USERNAME': '__token__',
                 'TWINE_PASSWORD': read_twine_token()},
                cwd=directory):
            return pr('Bad exit code from twine upload!', 'X')

    if args.force or version.parse(new_ver) > version.parse(get_aur_ver(title)):
        if not pause('publish to AUR', cancel=True):
            return

        # Calculate source targz checksums
        targz_checksum = sha256(directory.joinpath(
            'dist', f'{title}-{new_ver}.tar.gz'
        ).read_bytes()).hexdigest()

        # Locate hosted source targz
        hosted_targz = 'https://files.pythonhosted.org/packages/source/' + \
            f'{title[0]}/{title}/{title}' + '-${pkgver}.tar.gz'

        aur_subdir = directory.joinpath('aur')
        init = False
        if not aur_subdir.is_dir():
            pr('No "aur" subdirectory found, initiate?', '!')
            if not pause(cancel=True):
                return
            init = True

        pkgbuild = aur_subdir.joinpath('PKGBUILD')
        aur_remote_url = f'ssh://aur@aur.archlinux.org/python-{title}.git'
        if init:
            pr('Creating submodule named aur which will host AUR repo')
            aur_subdir.mkdir()
            subprocess.call(['git', 'init'], cwd=aur_subdir)
            subprocess.call(
                ['git', 'remote', 'add', 'aur', aur_remote_url],
                cwd=aur_subdir)

            pr('Using pip2pkgbuild to create a new PKGBUILD in ./aur dir')
            pkgbuild.write_bytes(subprocess.check_output(
                ['pip2pkgbuild', '-o', title]))
            # TODO Insert Maintainer tag
            pr('Created, go edit it as you see fit and then continue')
            if not pause(cancel=True):
                return
            # TODO Check with namcap

        else:
            # update_pkgbuild
            pr('Updating PKGBUILD with:')
            pr('\tsource = ' + hosted_targz)
            pr('\tsha256sum = ' + targz_checksum)
            with FileInput(pkgbuild, inplace=True) as file:
                for line in file:
                    if line.startswith('pkgver='):
                        old_ver = line.strip().split('=')[1]
                        print(line.replace(old_ver, new_ver), end='')
                    elif line.startswith('pkgrel='):
                        print(line.replace(line.strip().split('=')[1], '1'))
                    elif line.startswith('source=('):
                        s = line.split('(')[0] + '("'
                        print(s + hosted_targz + '")')
                    elif line.startswith('sha256sums=('):
                        s = line.split('(')[0] + '("'
                        print(s + targz_checksum + '")')
                    else:
                        print(line, end='')

        # makepkg_srcinfo
        pr('Dumping SRCINFO')
        with aur_subdir.joinpath('.SRCINFO').open('w') as srcinfo:
            if 0 != subprocess.call(['makepkg', '--printsrcinfo'],
                                    cwd=aur_subdir, stdout=srcinfo):
                return pr('Bad exit code from makepkg!', 'X')

        # Commit and push changes to AUR
        pr('Staging updated files')
        subprocess.call(['git', 'add', 'PKGBUILD', '.SRCINFO'],
                        cwd=aur_subdir)
        commit_msg = f'"Updated to v{new_ver}"'
        pr(f'Committing: {commit_msg}')
        subprocess.call(['git', 'commit', '-m', commit_msg],
                        cwd=aur_subdir)
        pr('Pushing to AUR!')
        subprocess.call(['git', 'push', '--set-upstream',
                         'aur', 'master'], cwd=aur_subdir)
        if init:
            pr('Registering a submodule "aur"')
            subprocess.call(
                ['git', 'submodule', 'add', aur_remote_url, 'aur'],
                cwd=directory)
