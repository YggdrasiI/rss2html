#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# Validators for user input
#

from ast import parse, walk
import _ast
from importlib.util import find_spec

import logging
logger = logging.getLogger(__name__)

# Declaration of allowed names for several statement types
WHITELIST = {
    _ast.ImportFrom: {
        "rss2html.feed": ["Feed"],
    },
    _ast.Import: [
        "sys",
        "os.path",
    ],
    _ast.Call: [
        "Feed", "print",
    ],
    _ast.Attribute: [
        "insert", "append", "update", "extend"
    ],
    _ast.Assign: [
        "FAVORITES", "HISTORY"
    ],
    _ast.Name: [
        "FAVORITES", "HISTORY"
    ],
}

class ValidatorException(Exception):
    pass


def validate_favorites(module_name=None, filepath=None, code=None):
    """ Validator for favorites*.py and user*.py-files

    Use only one of the arguments.
    • module_name: Module needs to be found in sys.path
    • filepath/code: Here we do not check if this would be the code
         lodad by an 'import …' statement.

    The input of the favorite/history-files can be influenced
    a) by user (url-field), and
    b) by RSS feed content (url, name, title fields)

    The input will be escaped, but as second barrier we check here
    if some code was injected.

    (Well, an alternative approach would be loading without interpretation
     as code…)
    """

    # Get filepath if module_name is given
    if module_name:
        assert filepath is None
        spec = find_spec(module_name)
        if not spec or not spec.origin:
            raise ValidatorException(
                    "No file found for module '{}'.".format(module_name))
        filepath = spec.origin

    # Load code if filepath was given
    if filepath:
        assert code is None
        with open(filepath, "r") as f:
            code = f.read(-1)

    # Generate code tree
    try:
        tree = parse(code, "<ast>")
    except Exception as e:
        raise ValidatorException(str(e))

    # Compare imports and function calls with whitelist.
    for child in walk(tree):
        if isinstance(child, _ast.ImportFrom):
            WLmodules = WHITELIST[type(child)]
            if not child.module in WLmodules:
                raise ValidatorException(
                        "Import from {} not allowed".format(child.module))
            WLnames = WLmodules[child.module]
            for aliasNode in child.names:
                if not aliasNode.name in WLnames:
                    raise ValidatorException(
                            "Import of {} not allowed".format(aliasNode.name))

        if isinstance(child, _ast.Import):
            WLpackages = WHITELIST[type(child)]
            for aliasNode in child.names:
                if not aliasNode.name in WLpackages:
                    raise ValidatorException(
                            "Import of {} not allowed".format(aliasNode.name))

        if isinstance(child, _ast.Call):
            if isinstance( child.func, _ast.Name ):
                # FOO = BAR
                WLcalls = WHITELIST[type(child)]
                if not child.func.id in WLcalls:
                    raise ValidatorException(
                            "Call of {} not allowed".format(child.func.id))

            elif isinstance( child.func, _ast.Attribute ):
                # FOO.append(BAR)
                WLattributes = WHITELIST[type(child.func)]
                WLname = WHITELIST[type(child.func.value)]
                if (not child.func.value.id in WLname or
                    not child.func.attr in WLattributes):
                    raise ValidatorException(
                            "Call of {} not allowed for {}".\
                        format(child.func.attr, child.func.value.id))


        if isinstance(child, _ast.Assign):
            WLvarnames = WHITELIST[type(child)]
            for t in child.targets:
                if not t.id in WLvarnames:
                    raise ValidatorException(
                            "Assign of {} not allowed".format(t.id))

    # No ValidatorException raised, thus…
    return True


if __name__ == "__main__":

    # Example code
    valid = '''\
from rss2html.feed import Feed

FAVORITES = [Feed("A", "url1"),
     Feed("B", "url4" + "ext" if True else "url5"),
    ]

HISTORY = [Feed("A", "url1"),
     Feed(url="swapped order", name="C"),
    ]
'''

    invalid_function_calls = '''\
HISTORY = [
    Feed("A", "url1") if (print("Gefahr!") or exec(compile("import os", "<test>", mode="exec"))) else Feed("X", "url1"),
]
'''

    invalid_indent = '''\
    HISTORY = [
    Feed("A", "url1") if (print("Gefahr!") or exec(compile("import os", "<test>", mode="exec"))) else Feed("X", "url1"),
]
'''

    invalid_import = '''\
import os
'''

    # Test reading from string
    for var in ["valid", "invalid_function_calls", "invalid_import", "invalid_indent"]:
        c = globals()[var]
        try:
            validate_favorites(code=c)
            print("'{}' is valid code\n".format(var))
        except ValidatorException as e:
            print("Invalid code found in '{}'".format(var))
            print("Error: {}\n".format(e))


    # Test reading from file and module
    import os.path
    test_file = "tmp_validators_test.py"

    assert not os.path.exists(test_file)  # Do not overwrite
    with open(test_file, "w") as f:
        f.write(valid)

    try:
        validate_favorites(filepath=test_file)
        print("'{}' contains valid code\n".format(test_file))
    except ValidatorException as e:
        print("Invalid code found in '{}'".format(test_file))
        print("Error: {}\n".format(e))

    try:
        module_name=os.path.splitext(test_file)[0]
        validate_favorites(module_name=module_name)
        print("'{}' is valid module\n".format(modul_name))
    except ValidatorException as e:
        print("Invalid code found in '{}'".format(modul_name))
        print("Error: {}\n".format(e))


    os.unlink(test_file)  # Clean up
