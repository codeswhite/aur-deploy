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


def pypi_procedure(directory: Path):
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


def update_pkgbuild_version(pkgbuild: Path, directory: Path, title: str, new_ver: str):
    # Calculate source targz checksums
    targz_checksum = sha256(directory.joinpath(
        'dist', f'{title}-{new_ver}.tar.gz'
    ).read_bytes()).hexdigest()

    # Locate hosted source targz
    hosted_targz = 'https://files.pythonhosted.org/packages/source/' + \
        f'{title[0]}/{title}/{title}' + '-${pkgver}.tar.gz'

    # update_pkgbuild
    pr('Updating PKGBUILD version with:')
    pr('\tpkgver = ' + new_ver)
    pr('\tpkgrel = 1')
    pr('\tsha256sum = ' + targz_checksum)
    with FileInput(pkgbuild, inplace=True) as file:
        for line in file:
            if line.startswith('pkgver='):
                old_ver = line.strip().split('=')[1]
                print(line.replace(old_ver, new_ver), end='')
            elif line.startswith('pkgrel='):
                print(line.replace(line.strip().split('=')[1], '1'), end='')
            elif line.startswith('sha256sums=('):
                s = line.split('(')[0] + '("'
                print(s + targz_checksum + '")')
            else:
                print(line, end='')


def aur_procedure(new_package: bool, aur_deps: iter, directory: Path, title: str, new_ver: str):
    aur_subdir = directory.joinpath('aur')
    create = False
    if not aur_subdir.is_dir():
        pr('No "aur" subdirectory found, initiate?', '!')
        if not pause(cancel=True):
            return
        create = True

    pkgbuild = aur_subdir.joinpath('PKGBUILD')
    aur_remote_url = f'ssh://aur@aur.archlinux.org/python-{title}.git'
    if not create:
        # Only update pkgbuild version info
        update_pkgbuild_version(pkgbuild, directory, title, new_ver)
    else:
        if not new_package:
            # clone
            pr('Cloning existing AUR repo')
            subprocess.call(
                ['git', 'clone', aur_remote_url, 'aur'], cwd=directory)

            # Update pkgbuild version info
            update_pkgbuild_version(pkgbuild, directory, title, new_ver)
        else:
            pr('Creating submodule named aur which will host AUR repo')
            aur_subdir.mkdir()
            subprocess.call(['git', 'init'], cwd=aur_subdir)
            subprocess.call(
                ['git', 'remote', 'add', 'aur', aur_remote_url],
                cwd=aur_subdir)

            # Get deps:
            requires = {'python-' + i for i in subprocess.check_output(
                ['python3', 'setup.py', '--requires'],
                cwd=directory).decode().splitlines()}
            lreq = len(requires)
            pr(f'Added {lreq} dependencies from setup.py')
            if aur_deps:
                requires.update(aur_deps)
                pr(f'Added {len(requires) - lreq} dependencies from arguments')
            for i in requires:
                print('\t', i)
            pr('Using pip2pkgbuild to create a new PKGBUILD in ./aur dir')
            pkgbuild.write_bytes(subprocess.check_output(
                ['pip2pkgbuild', '-d'] + list(requires) + ['-o', title]))
            # TODO Insert Maintainer tag

        pr('Created, go edit it as you see fit and then continue')
        if not pause(cancel=True):
            return
            # TODO Check with namcap

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
    remote_name = subprocess.check_output(['git', 'remote', 'show']).decode().strip()
    pr('Pushing to AUR!')
    subprocess.call(['git', 'push', '--set-upstream',
                     remote_name, 'master'], cwd=aur_subdir)
    if not create:
        return
    if 128 == subprocess.call(['git', 'status'], stdout=subprocess.DEVNULL, cwd=directory):
        pr('No git repo initialized so cannot register the "aur" submodule', '!')
        return
    pr('Registering a submodule "aur"')
    subprocess.call(
        ['git', 'submodule', 'add', aur_remote_url, 'aur'],
        cwd=directory)


def aur_deploy(args):
    directory = args.directory
    if directory.is_file():
        directory = directory.parent
    elif not directory.is_dir():
        return pr(f'No such file or directory {directory} !', 'X')
    pr(f'Running in: {directory} directory')
    if not directory.joinpath('setup.py').is_file():
        return pr('No setup.py found in directory, ' +
                  'Please prepare setup.py for deployment!', 'X')

    # Load setup.py
    title, new_ver, description = subprocess.check_output(
        ['python3', 'setup.py', '--name', '--version', '--description'],
        cwd=directory).decode().splitlines()
    pr(f'Project {title} {new_ver} in: {directory}')

    # Check PyPI
    if args.force or version.parse(new_ver) > version.parse(get_pypi_ver(title)):
        if not pause('publish to PyPI', cancel=True):
            return
        pypi_procedure(directory)
    
    # Check AUR
    if args.no_aur:
        return
    aur_ver = get_aur_ver(title)
    if args.force or version.parse(new_ver) > version.parse(aur_ver):
        if not pause('publish to AUR', cancel=True):
            return
        aur_procedure(aur_ver == '0', args.aur_depends,
                      directory, title, new_ver)
