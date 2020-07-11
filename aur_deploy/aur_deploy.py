from shutil import rmtree
import subprocess
from pathlib import Path
from hashlib import sha256
from packaging import version
from fileinput import FileInput

from interutils import pr, pause
from requests import get
from bs4 import BeautifulSoup


def read_twine_token():
    return Path(__file__).parent.joinpath('data', 'twine_token').read_text().strip()


def read_pkgbuild_template(pkgname, pkgver, pkgdesc):
    t = Path(__file__).parent.joinpath('data', 'pkgbuild_template').read_text()
    for k, v in {'<py_pkgname>': pkgname,
                 '<py_pkgver>': pkgver,
                 '<py_pkgdesc>': pkgdesc,
                 '<py_first_letter>': pkgname[0]}:
        t = t.replace(k, v)
    return t


def load_pypi(name):
    url = f'https://pypi.org/project/{name}/'
    res = get(url)
    if res.status_code != 200:
        print()
        pr('Bad response!', '!')
        return '0'
    bs = BeautifulSoup(res.text, features='html.parser')
    h1 = bs.find('h1', {"class": 'package-header__name'})
    return h1.get_text(strip=True).split()[-1]  # Version


def load_aur(name):
    url = f'https://aur.archlinux.org/packages/python-{name}/'
    res = get(url)
    if res.status_code != 200:
        print()
        pr('Bad response!', '!')
        return '0'
    bs = BeautifulSoup(res.text, features='html.parser')
    d = bs.find('div', {"id": 'pkgdetails'})
    h2 = d.find('h2')
    return h2.get_text(strip=True).split()[-1]  # Version


def aur_deploy(directory):
    if not directory.joinpath('setup.py').is_file():
        return pr('No setup.py found in current directory!', 'X')

    # Load setup.py
    title, new_ver, description = subprocess.check_output(
        ['python3', 'setup.py', '--name', '--version', '--description'],
        cwd=directory).decode().splitlines()
    pr(f'Project {title} {new_ver} in: {directory}')

    # Check PyPI
    pr('Checking PyPI: ', end='')
    pypi_ver = load_pypi(title)
    print(pypi_ver)
    if version.parse(new_ver) > version.parse(pypi_ver):
        if not pause('publish to PyPI', cancel=True):
            return

        # Clean build and dist
        for f in directory.iterdir():
            if f.name in ('build', 'dist'):
                pr('Removing: ', f)
                rmtree(f)

        # Build wheel
        pr('Building wheel')
        if 0 != subprocess.call(['python3', './setup.py', 'sdist', 'bdist_wheel'],
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
        if 0 != subprocess.call(['python3', '-m', 'twine', 'upload', './dist/*'],
                                env={'TWINE_USERNAME': '__token__',
                                     'TWINE_PASSWORD': read_twine_token()},
                                cwd=directory):
            return pr('Bad exit code from twine upload!', 'X')

    pr('Checking AUR: ', end='')
    aur_ver = load_aur(title)
    print(aur_ver)
    if version.parse(new_ver) > version.parse(aur_ver):
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
        if init:
            aur_subdir.mkdir()
            pkgbuild.write_text(read_pkgbuild_template(
                title, new_ver, description))
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
                         'origin', 'master'], cwd=aur_subdir)

