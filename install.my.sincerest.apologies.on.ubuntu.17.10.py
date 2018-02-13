#!/usr/bin/env python3

import os.path
from os.path import exists, basename
import sys


print("This script will install My Sincerest Apologies in the")
print("'apologies' subdirectory of the current directory:")
print("   ", os.getcwd() + "/apologies")
print()
input("[Press Enter to continue or Ctrl-C to abort> ")


def header():
    print()
    print()
    print("_" * 79)
    print("_" * 79)
    print()

def packages_failed(*failed):
    header()
    print("Couldn't install all packages!  Failed to install:")
    print("   ", " ".join(failed))
    sys.exit("Sorry, this script can't handle this.  Maybe you're not on the network?")



os.system("sudo apt install update")

install_test_map = {

"g++" : "/usr/bin/g++",
"gcc" : "/usr/bin/gcc",
"git" : "/usr/bin/git",
"libffi-dev" : "/usr/lib/x86_64-linux-gnu/libffi.so",
"libglu1-mesa-dev" : "/usr/lib/x86_64-linux-gnu/libGLU.so",
"libopenal1" : "/usr/lib/x86_64-linux-gnu/libopenal.so.1",
"python3-dev" : "/usr/share/doc/python3-dev",
"python3-venv" : "/usr/bin/pyvenv",

}

os.system("sudo apt install -y " + " ".join(install_test_map))

failed = []
for package, filename in install_test_map.items():
    if not exists(filename):
        failed.append(package)

if failed:
    packages_failed(*failed)

os.system("python3 -m venv apologies")
if not exists("apologies/bin/activate"):
    header()
    sys.exit("Couldn't create apologies venv!  I have no idea why this failed.")


os.chdir("apologies")

platform_bits = "64" if sys.maxsize > 2**32 else "32"

avbin_url = "https://github.com/downloads/AVbin/AVbin/install-avbin-linux-x86-" + platform_bits + "-v10"
avbin_filename = basename(avbin_url)
os.system("wget " + avbin_url)
os.system("sudo sh " + avbin_filename)

if not exists("/usr/lib/libavbin.so"):
    packages_failed("AVBin")


os.system("git clone https://github.com/larryhastings/pyweek24.git")
if not exists("pyweek24"):
    header()
    sys.exit("Couldn't clone pyweek24 repo!  Are you on the network?")

with open("pyweek24/requirements.txt", "rt") as f:
    requirements = [line.partition('=')[0] for line in f.read().split()]

with open("import.test.py", "wt") as f:
    def p(s): print(s, file=f)
    for package in requirements:
        p("import " + package)
    p('with open("python.success.txt", "wt") as f:')
    p('    f.write("Success!\\n")')
    p('print("All Python packages installed.  Phew!")')

files_map = {
"child.install.sh": """

#!/usr/bin/env bash

. bin/activate
cd pyweek24
../bin/pip install -r requirements.txt
cd ..
bin/python3 import.test.py
""",

"run_game": """

#!/usr/bin/env bash

. bin/activate
cd pyweek24
../bin/python3 run_game.py

""",

}

for filename, text in files_map.items():
    with open(filename, "wt") as f:
        f.write(text.lstrip() + "\n")
    os.chmod(filename, 0o755)


os.system("sh child.install.sh")

if not exists("python.success.txt"):
    header()
    sys.exit("Couldn't install all Python packages.\nI have no idea how to fix this, sorry!")

#
# it all worked! clean up.
#

for filename in """
import.test.py
python.success.txt
child.install.sh
""".strip().split():
    os.unlink(filename)
os.unlink(avbin_filename)

header()
print("Ready!  cd into the 'apologies' directory and run")
print("    % ./run_game")
print("to play My Sincerest Apologies!")
print()
