#!/usr/bin/python3
# -*- coding: utf-8 -*-
#

import sys
import os
import os.path
import re
from subprocess import call

def create_venv():
    if not os.path.isdir("venv"):
        cmd = ["python.exe", "-m", "venv", "venv"]
        call(cmd)
        print("Virtual environment created")
        return True

    return False


def create_requirements_txt():
    packages = []
    begin_adding = False
    with open("setup.cfg") as f:
        l = f.readline()
        while l:
            l = l.rstrip('\n\r')
            if l.startswith("install_requires ="):
                begin_adding = True
            elif begin_adding:
                if re.match("^\s+[^#]", l):
                    name = re.match("^\s+([^#<>=]+)", l)
                    if name:
                        packages.append(name.group(1))
                if l.strip() == "" or l[0] not in [" ", "\t"]:
                    # begin_adding = False
                    break

            l = f.readline()
    if len(packages) > 0:
        with open("requirements.txt", "w") as fout:
            for p in packages:
                fout.write(p + "\n")

    print("requirements.txt created")
    return True


def install_dependencies():    
    cmd = ["venv/Scripts/python.exe",
            "-m", "pip", "install", "-U",
            "-r", "requirements.txt"]

    call(cmd)
    print("Dependencies installed")
    return True


def start_rss2html(host):
    # PYTHONPATH="src" venv/Scripts/python.exe -m rss2html --host "127.0.0.1"
    my_env = os.environ.copy()
    python_path = my_env.get("PYTHONPATH", "")
    my_env["PYTHONPATH"] = '{}{}'.format(
            os.path.abspath('src'),
            (":"+ python_path) if python_path else "")
    # Attention PYTHONPATH '../src:' leads to wrong path including ':'

    cmd = ["venv/Scripts/python.exe",
            "-m", "rss2html"]
    if host:
        cmd.extend(["--host", host])

    #print(my_env["PYTHONPATH"])
    #print(cmd)
    call(cmd, env=my_env)



if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv)>1 else None

    if create_venv():
        create_requirements_txt()
        install_dependencies()

    start_rss2html(host)
