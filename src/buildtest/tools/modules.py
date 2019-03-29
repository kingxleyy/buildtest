############################################################################
#
#  Copyright 2017-2019
#
#   https://github.com/HPC-buildtest/buildtest-framework
#
#  This file is part of buildtest.
#
#    buildtest is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    buildtest is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with buildtest.  If not, see <http://www.gnu.org/licenses/>.
#############################################################################

"""
This python module does the following
	 - get module listing
	 - get unique application
	 - get unique application version
 	 - check if software exists based on argument -s
	 - check if toolchain exists based on argument -t
	 - check if easyconfig passes
"""
import json
import os
import sys
import subprocess
import yaml
from buildtest.tools.config import config_opts, BUILDTEST_CONFIG_FILE
from buildtest.tools.file import string_in_file, is_dir




def func_module_subcmd(args):
    """ entry point for module subcommand """

    if args.diff_trees:
        diff_trees(args.diff_trees)
    if args.module_load_test:
        module_load_test()
    if args.list:
        for tree in config_opts["BUILDTEST_MODULE_ROOT"]:
            print (tree)
    if args.add:
        is_dir(args.add)
        fd = open(BUILDTEST_CONFIG_FILE,"r")
        content = yaml.load(fd)
        fd.close()

        content["BUILDTEST_MODULE_ROOT"].append(args.add)
        # converting to set to avoid adding duplicate entries
        module_tree_set = set(content["BUILDTEST_MODULE_ROOT"])
        module_tree_set.add(args.add)

        content["BUILDTEST_MODULE_ROOT"] = list(module_tree_set)

        fd = open(BUILDTEST_CONFIG_FILE,"w")
        yaml.dump(content,fd,default_flow_style=False)
        fd.close()

        print (f"Adding module tree: {args.add}")
        print (f"Configuration File: {BUILDTEST_CONFIG_FILE} has been updated")
    if args.rm:
        fd = open(BUILDTEST_CONFIG_FILE,"r")
        content = yaml.load(fd)
        content["BUILDTEST_MODULE_ROOT"].remove(args.rm)
        fd.close()

        fd = open(BUILDTEST_CONFIG_FILE,"w")
        yaml.dump(content,fd,default_flow_style=False)
        fd.close()
        print (f"Removing module tree: {args.rm}")
        print (f"Configuration File: {BUILDTEST_CONFIG_FILE} has been updated")

class BuildTestModule():
    def __init__(self):

        self.moduletree = ':'.join(map(str,config_opts["BUILDTEST_MODULE_ROOT"] ))

        cmd = f"$LMOD_DIR/spider -o spider-json {self.moduletree}"
        out = subprocess.check_output(cmd, shell=True).decode("utf-8")
        self.module_dict = json.loads(out)

    def get_module_spider_json(self):
        return self.module_dict
    def get_unique_modules(self):
        """Return a list of unique full name canonical modules """
        return sorted(self.module_dict.keys())
    def get_unique_software_modules(self):
        """Return a set with list of unique software module names"""
        software_set = set()
        sorted_keys = sorted(self.module_dict.keys())
        for k in sorted_keys:
            for mod_file in self.module_dict[k].keys():
                software_set.add(self.module_dict[k][mod_file]["full"])

        return sorted(list(software_set))
    def check_module(self,module):
        """Check if module is in list of unique_software_modules and return
        True or False"""
        if module in self.get_unique_modules():
            return True
        else:
            return False
    def get_parent_modules(self,modname):
        """Get Parent module for specified module file."""
        for key in self.module_dict.keys():
            for mod_file in self.module_dict[key].keys():
                print (key,self.module_dict[key])
                if modname == self.module_dict[key][mod_file]["full"]:

                    mod_parent_list = self.module_dict[key][mod_file]["parent"]
                    parent_module = []
                    # parent: is a list, only care about one entry which
                    # contain list of modules to be loaded separated by :
                    # First entry is default:<mod1>:<mod2> so skip first
                    # element
                    for entry in mod_parent_list[0].split(":")[1:]:
                        parent_module.append(entry)
                    return parent_module

        return []
def strip_toolchain_from_module(modulename):
    """When module file has toolchain in version remove it (ex.  Python/2.7.14-intel-2018a  should return  Python/2.7.14 )"""
    from buildtest.tools.software import get_toolchain_stack

    toolchain_stack = get_toolchain_stack()
    toolchain_name = [name.split("/")[0] for name in toolchain_stack]
    # get module version
    module_version = modulename.split("/")[1]

    app_name = modulename.split("/")[0]
    # if application is a toolchain then return modulename as is without stripping toolchain
    if app_name in toolchain_name:
        return modulename
    # remove any toolchain from module version when figuring path to yaml file
    for tc in toolchain_name:
        idx = module_version.find(tc)

        if idx != -1:
            modulename_strip_toolchain = modulename.split("/")[0] + "/" + module_version[0:idx-1]
            return modulename_strip_toolchain

def get_module_list():
    """returns a list of modules from module tree with fullpath to module file. """
    modulefiles = []
    modtrees = config_opts["BUILDTEST_MODULE_ROOT"]
    for tree in modtrees:
        is_dir(tree)
        for root, dirs, files in os.walk(tree):
            for file in files:
                # only add modules with .lua extension or files that have #%Module as part of first line
                if file.endswith(".lua"):
                    modulefiles.append(os.path.join(root,file))

    return modulefiles

def get_module_list_by_tree(mod_tree):
    """ returns a list of module file paths given a module tree """

    modulefiles = []

    is_dir(mod_tree)
    for root, dirs, files in os.walk(mod_tree):
        for file in files:
            if file.endswith(".lua") or string_in_file("#%Module",os.path.join(root,file)):
                modulefiles.append(os.path.join(root,file))

    return modulefiles

module_obj = BuildTestModule()
def module_load_test():
    """perform module load test for all modules in BUILDTEST_MODULE_ROOT"""

    #module_obj = BuildTestModule()
    module_stack = module_obj.get_unique_software_modules()

    for mod_file in module_stack:
        cmd = "module purge"

        parent_modules = module_obj.get_parent_modules(mod_file)
        for item in parent_modules:
            cmd += "module try-load {} ".format(item)
        cmd +=  "module load " + mod_file

        ret = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        ret.communicate()

        if ret.returncode == 0:
            print ("STATUS: PASSED - Testing module: ", mod_file)
        else:
            print ("STATUS: FAILED - Testing module: ", mod_file)

    sys.exit(0)

def diff_trees(args_trees):
    """ display difference between module trees """

    # no comma found between two trees
    if args_trees.find(",") == -1:
        print ("Usage: --diff-trees /path/to/tree1,/path/to/tree2")
        sys.exit(1)
    else:
        id = args_trees.find(",")
        tree1 = args_trees[0:id]
        tree2 = args_trees[id+1:len(args_trees)]

        is_dir(tree1)
        is_dir(tree2)

        modlist1 = []
        modlist2 = []

        list1 = get_module_list_by_tree(tree1)
        list2 = get_module_list_by_tree(tree2)

        # strip full path, just get a list module file in format app/version
        for file in list1:
            name = os.path.basename(os.path.dirname(file))
            # strip out any file extension (.lua)
            ver = os.path.basename(os.path.splitext(file)[0])
            modlist1.append(os.path.join(name,ver))

        for file in list2:
            name = os.path.basename(os.path.dirname(file))
            # strip out any file extension (.lua)
            ver = os.path.basename(os.path.splitext(file)[0])
            modlist2.append(os.path.join(name,ver))

        # convert list into set and do symmetric difference between two sets
        diff_set =  set(modlist1).symmetric_difference(set(modlist2))
        if len(diff_set) == 0:
            print ("No difference found between module tree: ", tree1, " and module tree: ", tree2)
        # print difference between two sets by printing module file and stating  FOUND or NOTFOUND in the appropriate columns for Module Tree 1 or 2
        else:
            print ("\t\t\t Comparing Module Trees for differences in module files")
            print ("\t\t\t -------------------------------------------------------")

            print
            print ("Module Tree 1: ", tree1)
            print ("Module Tree 2: ", tree2)
            print
            print ("ID       |     Module                                                   |   Module Tree 1    |   Module Tree 2")
            print ("---------|--------------------------------------------------------------|--------------------|----------------------")

            count = 1
            # print difference set
            for i in diff_set:
                module_in_tree = ""
                value1 = "NOT FOUND"
                value2 = "NOT FOUND"
                # finding which module tree the module belongs
                if i in modlist1:
                    module_in_tree = tree1
                if i in modlist2:
                    module_in_tree = tree2

                if module_in_tree == tree1:
                    value1 = "FOUND"

                if module_in_tree == tree2:
                    value2 = "FOUND"


                print ((str(count) + "\t |").expandtabs(8), (i + "\t |").expandtabs(60) , (value1 + "\t |").expandtabs(18), value2)
                count = count + 1
