from shutil import rmtree
from os import rename
from subprocess import call, check_output, DEVNULL
from pathlib import Path
from hashlib import sha256
from packaging import version
from fileinput import FileInput

from interutils import pr, pause
from requests import get
from bs4 import BeautifulSoup


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


def build_wheel(directory: Path):
    # Build wheel
    pr('Building wheel')
    if 0 != call(
        ['python3', './setup.py', 'sdist', 'bdist_wheel'],
            cwd=directory, stdout=DEVNULL):
        return pr('Bad exit code from setup bulid wheel!', 'X')

    # Check via twine
    pr('Checking via twine')
    if 0 != call(
            ['python3', '-m', 'twine', 'check', './dist/*'], cwd=directory):
        return pr('Bad exit code from twine check!', 'X')

    return True  # Success


def pypi_procedure(directory: Path):
    # Check pypirc
    if not (Path.home() / '.pypirc').is_file():
        return pr('No ~/.pypirc found! please configure twine!', 'X')

    # Clean build and dist
    for f in directory.iterdir():
        if f.name in ('build', 'dist'):
            pr(f'Removing: {f}')
            rmtree(f)

    if not build_wheel(directory):
        return 0

    # Publish via twine
    pr('Publishing via twine')
    if 0 != call(
            ['python3', '-m', 'twine', 'upload', './dist/*'], cwd=directory):
        return pr('Bad exit code from twine upload!', 'X')

    return True  # Success


def update_pkgbuild_version(pkgbuild: Path, directory: Path, title: str, new_ver: str):
    # Calculate source targz checksums
    pr('Calculating SHA256 sum of distributed tarball')
    tarball = directory.joinpath('dist', f'{title}-{new_ver}.tar.gz')
    if not tarball.is_file():
        pr('Tarball not found, building..')
        if not build_wheel(directory):
            return

    targz_checksum = sha256(tarball.read_bytes()).hexdigest()

    # update_pkgbuild
    pr(f'Updating PKGBUILD version to {new_ver}')
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
    return True  # Success


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
        if not update_pkgbuild_version(pkgbuild, directory, title, new_ver):
            return
    else:
        if not new_package:
            # clone
            pr('Cloning existing AUR repo')
            call(
                ['git', 'clone', aur_remote_url, 'aur'], cwd=directory)

            # Update pkgbuild version info
            if not update_pkgbuild_version(pkgbuild, directory, title, new_ver):
                return
        else:
            pr('Creating submodule named aur which will host AUR repo')
            aur_subdir.mkdir()
            call(['git', 'init'], cwd=aur_subdir)
            call(
                ['git', 'remote', 'add', 'aur', aur_remote_url], cwd=aur_subdir)

            # Get deps:
            requires = {'python-' + i for i in check_output(
                ['python3', 'setup.py', '--requires'], cwd=directory).decode().splitlines()}
            lreq = len(requires)
            pr(f'Added {lreq} dependencies from setup.py')
            if aur_deps:
                if 'python' in aur_deps:
                    aur_deps.remove('python')
                requires.update(aur_deps)
                pr(f'Added {len(requires) - lreq} dependencies from cli arguments')
            for i in requires:
                print('\t', i)
            pr('Using pip2pkgbuild to create a new PKGBUILD in ./aur directory')
            pkgbuild.write_bytes(check_output(
                ['pip2pkgbuild', '-d'] + list(requires) + ['-o', title]))
            # TODO Insert Maintainer tag

        pr('Created, go edit it as you see fit and then continue')
        if not pause(cancel=True):
            return
            # TODO Check with namcap

    # makepkg_srcinfo
    pr('Dumping SRCINFO')
    with aur_subdir.joinpath('.SRCINFO').open('w') as srcinfo:
        if 0 != call(['makepkg', '--printsrcinfo'], cwd=aur_subdir, stdout=srcinfo):
            return pr('Bad exit code from makepkg!', 'X')

    # Commit and push changes to AUR
    branch_name = check_output(
        ['git', 'branch', '--show-current'], cwd=aur_subdir).decode().strip()
    if branch_name != 'master': # Currently AUR declines other names
        pr(f'Renaming branch: {branch_name} to "master" (per AUR policy)')
        call(['git', 'branch', '-m', 'master'], cwd=aur_subdir)
        branch_name = check_output(
            ['git', 'branch', '--show-current'], cwd=aur_subdir).decode().strip()

    pr('Staging updated files')
    call(['git', 'add', 'PKGBUILD', '.SRCINFO'], cwd=aur_subdir)
    commit_msg = f'"Updated to v{new_ver}"'

    pr(f'Committing: {commit_msg}')
    call(['git', 'commit', '-m', commit_msg], cwd=aur_subdir)

    pr('Pushing to AUR!')
    remote_name = check_output(
        ['git', 'remote', 'show'], cwd=aur_subdir).decode().strip()
    call(['git', 'push', '--set-upstream',
          remote_name, branch_name], cwd=aur_subdir)
    if create:
        if 128 == call(['git', 'status'], stdout=DEVNULL, cwd=directory):
            return pr('No git repo initialized so cannot register the "aur" submodule', '!')
        pr('Registering a submodule "aur"')
        call(['git', 'submodule', 'add',
              aur_remote_url, 'aur'], cwd=directory)
    return 1  # Success


def aur_deploy(args):
    if args.directory:
        directory = Path(args.directory)
        if directory.is_file():
            directory = directory.parent
    else:
        directory = Path.cwd()
    if not directory.is_dir():
        pr(f'Cnnot run in directory, No such directory {directory} !', 'X')
        return 1

    pr(f'Running in: {directory} directory')
    if not directory.joinpath('setup.py').is_file():
        pr('No setup.py found in directory, ' +
           'Please prepare setup.py for deployment!', 'X')
        return 1

    # Load setup.py
    title, new_ver, description = check_output(['python3', 'setup.py', '--name', '--version', '--description'],
                                               cwd=directory).decode().splitlines()
    pr(f'Project {title} {new_ver} in: {directory}')

    # Check PyPI
    if args.force or version.parse(new_ver) > version.parse(get_pypi_ver(title)):
        if not pause('publish to PyPI', cancel=True) \
                or not pypi_procedure(directory):
            return 1

    # Check AUR
    if args.no_aur:
        return
    aur_ver = get_aur_ver(title)
    if args.force or version.parse(new_ver) > version.parse(aur_ver):
        if not pause('publish to AUR', cancel=True) \
            or not aur_procedure(aur_ver == '0', args.aur_depends,
                                 directory, title, new_ver):
            return 1
