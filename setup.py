import setuptools
import pathlib

here = pathlib.Path(__file__).parent.resolve()
long_description = (here / 'README.md').read_text(encoding='utf-8')

setuptools.setup(
    name="aur-deploy",
    version="0.8.6",
    description="Automate updating pkgbuild and deploying to AUR",
    url="https://github.com/codeswhite/aur-deploy",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools'
    ],
    keywords='aur, archlinux, build, deploy, publish',
    python_requires='>=3.6',
    install_requires=[
        'interutils',
        'requests',
        'bs4'
    ],
    entry_points={
        'console_scripts': [
            'aur-deploy=aur_deploy:main',
        ],
    },
    author="Max G",
    author_email="max3227@gmail.com",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
)
