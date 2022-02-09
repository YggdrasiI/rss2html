#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Plugin for lesscpy to get same result as lessc+plugin_css_invert.py
#
# TLDR: Use lessc! The parsing capabilities of lesscpy are weak and
#       this simple compiling task is just possible with this
#       ugly workaround.
#
#       python3 plugin_css_invert dark.less dark.tmp.less
#       lesscpy dark.tmp.less > dark.tmp.css
#       sed "s/DOUBLEHYPHEN/--/g" dark_tmp.css > dark.css
#
# No general solution, but good enough for this less-files...
#
# Supported inputs syntax:
# css_invert(rgb(  0,   0,   0), @factor);
# css_invert(rgba(99,99,99,0.1), @factor);
# css_invert(#F2DC95, @factor);

import sys
import os.path
import re
import fileinput

# Rebuild of CSS's filter: invert(percentage)
#
# It provides following change on each rgb channel:
#     255 - [255*(1-p) + x*(2*p-1)]
#
FNAME = "css_invert"
def formel(r,g,b, p):
    # Apply  255 - [255*(1-p) + x*(2*p-1)] on all colors.
    r = 255 - (255*(1-p) + r*(2*p-1))
    g = 255 - (255*(1-p) + g*(2*p-1))
    b = 255 - (255*(1-p) + b*(2*p-1))
    return (r,g,b)

def remove_at_plugin(lines):
    # @plugin "plugin_css_invert";
    pl_lines = re.compile("\s*@plugin[^;]*;")
    for i in range(len(lines)):
        lines[i] = pl_lines.sub("", lines[i], 100)

def is_varname(s):
    return s[0] == "@"

def find_value(name, lines, lstart=0, lend=-1):
    # @factor: 0.85;
    value = re.compile("@{}:\s*(\S+);".format(name))
    if lend<0:
        lend = len(lines) + lend

    ret = None
    for l in lines[lstart:lend]:
        m = value.match(l)
        if m:
            try:
                ret = float(m.group(1))
            except ValueError:
                # Recursion not supported
                pass

    return ret


def replace_fname(lines):
     # css_invert(rgb(148, 145, 141), @factor);
    variante1 = re.compile(
        "{}\s*\(rgb\(\s*([0-9]+),\s*([0-9]+),\s*([0-9]+)\),\s*@(\S+)\)".\
            format(FNAME))

    # css_invert(rgba(99,99,99,0.1), @factor);
    variante2 = re.compile(
        "{}\(rgba\(\s*([0-9]+),\s*([0-9]+),\s*([0-9]+),\s*([^)]+)\),\s*@(\S+)\)".\
            format(FNAME))

    # css_invert(#F2DC95, @factor);               
    variante3 = re.compile(
        "{}\(#([0-9A-Fa-f][0-9A-Fa-f])([0-9A-Fa-f][0-9A-Fa-f])([0-9A-Fa-f][0-9A-Fa-f])\s*,\s*@(\S+)\)".\
            format(FNAME))

    for i in range(len(lines)):
        l = lines[i]
        m = variante1.search(l)
        if m:
            r = int(m.group(1))
            g = int(m.group(2))
            b = int(m.group(3))
            p = find_value(m.group(4), lines)
            (r,g,b) = formel(r,g,b,p)

            l2 = "{}rgb({:1.0f}, {:1.0f}, {:1.0f}){}".format(
                l[:m.span()[0]],
                r, g, b,
                l[m.span()[1]:],
            )
            # print("C", l2)
            lines[i] = l2

        m = variante2.search(l)
        if m:
            r = int(m.group(1))
            g = int(m.group(2))
            b = int(m.group(3))
            a = m.group(4)
            p = find_value(m.group(5), lines)
            (r,g,b) = formel(r,g,b,p)

            l2 = "{}rgba({:1.0f}, {:1.0f}, {:1.0f}, {}){}".format(
                l[:m.span()[0]],
                r, g, b, a,
                l[m.span()[1]:],
            )
            # print("D", l2)
            lines[i] = l2

        m = variante3.search(l)
        if m:
            r = int(m.group(1), base=16)
            g = int(m.group(2), base=16)
            b = int(m.group(3), base=16)
            p = find_value(m.group(4), lines)
            (r,g,b) = formel(r,g,b,p)

            l2 = "{}rgb({:1.0f}, {:1.0f}, {:1.0f}){}".format(
                l[:m.span()[0]],
                r, g, b,
                l[m.span()[1]:],
            )
            # print("E", l2)
            lines[i] = l2
                                        
def lesscpy_do_not_compile_varnames(lines):
    # Hm, --varname is not supported *dang*
    # This substitution needs to be inverted after lesscpy call.
    for i in range(len(lines)):
        lines[i] = lines[i].replace("--", "DOUBLEHYPHEN")

def main(infile, outfile):
    lines = []
    if outfile == "-":
        outfile = None

    for l in fileinput.input(files=[infile]):
        lines.append(l)

    remove_at_plugin(lines)

    replace_fname(lines)

    lesscpy_do_not_compile_varnames(lines)

    if outfile is None:
        for l in lines:
            print(l)
    else:
        with open(outfile, "w") as fout:
            for l in lines:
                fout.write(l)


if __name__ == "__main__":
    infile = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv)>2 else None

    main(infile, outfile)


