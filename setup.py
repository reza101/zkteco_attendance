from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = [l.strip() for l in f if l.strip() and not l.startswith("#")]

setup(
    name="zkteco_attendance",
    version="0.2.0",
    description="ZKTeco ADMS attendance device integration for ERPNext HR",
    author="webmajors",
    author_email="webmajors.com@gmail.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
