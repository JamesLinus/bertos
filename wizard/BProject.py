#!/usr/bin/env python
# encoding: utf-8
#
# This file is part of BeRTOS.
#
# Bertos is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
# As a special exception, you may use this file as part of a free software
# library without restriction.  Specifically, if other files instantiate
# templates or use macros or inline functions from this file, or you compile
# this file and link it with other files to produce an executable, this
# file does not by itself cause the resulting executable to be covered by
# the GNU General Public License.  This exception does not however
# invalidate any other reasons why the executable file might be covered by
# the GNU General Public License.
#
# Copyright 2008 Develer S.r.l. (http://www.develer.com/)
#
# $Id$
#
# Author: Lorenzo Berni <duplo@develer.com>
#

import os
import fnmatch
import copy
import pickle

import DefineException

from LoadException import VersionException, ToolchainException

import const

from bertos_utils import (
                            # Utility functions
                            isBertosDir, getTagSet, getInfos, updateConfigurationValues,
                            loadConfigurationInfos, loadDefineLists, loadModuleDefinition,
                            getCommentList,

                            # Custom exceptions
                            ParseError, SupportedException
                        )

class BProject(object):
    """
    Simple class for store and retrieve project informations.
    """

    def __init__(self, project_file="", info_dict={}):
        self.infos = {}
        self._cached_queries = {}
        if project_file:
            self.loadBertosProject(project_file, info_dict)

    #--- Load methods (methods that loads data into project) ------------------#

    def loadBertosProject(self, project_file, info_dict):
        project_dir = os.path.dirname(project_file)
        project_data = pickle.loads(open(project_file, "r").read())
        # If PROJECT_NAME is not defined it use the directory name as PROJECT_NAME
        # NOTE: this can throw an Exception if the user has changed the directory containing the project
        self.infos["PROJECT_NAME"] = project_data.get("PROJECT_NAME", os.path.basename(project_dir))
        self.infos["PROJECT_PATH"] = os.path.dirname(project_file)
        
        # Check for the Wizard version
        wizard_version = project_data.get("WIZARD_VERSION", 0)
        if wizard_version < 1:
            # Ignore the SOURCES_PATH inside the project file for older projects
            project_data["SOURCES_PATH"] = project_dir
        self.loadBertosSourceStuff(project_data, info_dict.get("SOURCES_PATH", None))
        
        # For those projects that don't have a VERSION file create a dummy one.
        if not isBertosDir(project_dir):
            version_file = open(os.path.join(const.DATA_DIR, "vtemplates/VERSION"), "r").read()
            open(os.path.join(project_dir, "VERSION"), "w").write(version_file.replace("$version", "").strip())
            
        self.loadSourceTree()
        self.loadCpuStuff(project_data)
        self.loadToolchainStuff(project_data, info_dict.get("TOOLCHAIN", None))
        self.infos["OUTPUT"] = project_data["OUTPUT"]
        self.loadModuleData(True)
        self.setEnabledModules(project_data["ENABLED_MODULES"])

    def loadBertosSourceStuff(self, project_data, forced_version=None):
        bertos_source_path = project_data["SOURCES_PATH"]
        if forced_version:
            bertos_source_path = forced_version
        if os.path.exists(bertos_source_path):
            self.infos["SOURCES_PATH"] = bertos_source_path
        else:
            raise VersionException(self)

    def loadCpuStuff(self, project_data):
        cpu_name = project_data["CPU_NAME"]
        self.infos["CPU_NAME"] = cpu_name
        cpu_info = self.getCpuInfos()
        for cpu in cpu_info:
            if cpu["CPU_NAME"] == cpu_name:
                self.infos["CPU_INFOS"] = cpu
                break
        tag_list = getTagSet(cpu_info)
        # Create, fill and store the dict with the tags
        tag_dict = {}
        for element in tag_list:
            tag_dict[element] = False
        infos = self.info("CPU_INFOS")
        for tag in tag_dict:
            if tag in infos["CPU_TAGS"] + [infos["CPU_NAME"], infos["TOOLCHAIN"]]:
                tag_dict[tag] = True
            else:
                tag_dict[tag] = False
        self.infos["ALL_CPU_TAGS"] = tag_dict
        self.infos["SELECTED_FREQ"] = project_data["SELECTED_FREQ"]

    def loadToolchainStuff(self, project_data, forced_toolchain=None):
        toolchain = project_data["TOOLCHAIN"]
        if forced_toolchain:
            toolchain = forced_toolchain
        if os.path.exists(toolchain["path"]):
            self.infos["TOOLCHAIN"] = toolchain
        else:
            raise ToolchainException(self)

    def loadProjectFromPreset(self, preset):
        """
        Load a project from a preset.
        NOTE: this is a stub.
        """
        self.loadBertosProject(os.path.join(preset, 'project.bertos'), {})

    def loadProjectPresets(self):
        """
        Load the default presets (into the const.PREDEFINED_BOARDS_DIR).
        """
        # NOTE: this method does nothing (for now).
        preset_path = os.path.join(self.infos["SOURCES_PATH"], const.PREDEFINED_BOARDS_DIR)
        preset_tree = {}
        if os.path.exists(preset_path):
            preset_tree = self._loadProjectPresetTree(preset_path)
        self.infos["PRESET_TREE"] = preset_tree

    def _loadProjectPresetTree(self, path):
        _tree = {}
        _tree['info'] = self._loadPresetInfo(os.path.join(path, const.PREDEFINED_BOARD_SPEC_FILE))
        _tree['info']['filename'] = os.path.basename(path)
        _tree['info']['path'] = path
        _tree['children'] = []
        entries = set(os.listdir(path))
        for entry in entries:
            _path = os.path.join(path, entry)
            if os.path.isdir(_path):
                sub_entries = set(os.listdir(_path))
                if const.PREDEFINED_BOARD_SPEC_FILE in sub_entries:
                    _tree['children'].append(self._loadProjectPresetTree(_path))
        # Add into the info dict the dir type (dir/project)
        if _tree['children']:
            _tree['info']['type'] = 'dir'
        else:
            _tree['info']['type'] = 'project'
        return _tree

    def _loadPresetInfo(self, preset_spec_file):
        D = {}
        execfile(preset_spec_file, {}, D)
        return D

    def loadModuleData(self, edit=False):
        module_info_dict = {}
        list_info_dict = {}
        configuration_info_dict = {}
        file_dict = {}
        for filename, path in self.findDefinitions("*.h") + self.findDefinitions("*.c") + self.findDefinitions("*.s") + self.findDefinitions("*.S"):
            comment_list = getCommentList(open(path + "/" + filename, "r").read())
            if len(comment_list) > 0:
                module_info = {}
                configuration_info = {}
                try:
                    to_be_parsed, module_dict = loadModuleDefinition(comment_list[0])
                except ParseError, err:
                    raise DefineException.ModuleDefineException(path, err.line_number, err.line)
                for module, information in module_dict.items():
                    if "depends" not in information:
                        information["depends"] = ()
                    information["depends"] += (filename.split(".")[0],)
                    information["category"] = os.path.basename(path)
                    if "configuration" in information and len(information["configuration"]):
                        configuration = module_dict[module]["configuration"]
                        try:
                            configuration_info[configuration] = loadConfigurationInfos(self.infos["SOURCES_PATH"] + "/" + configuration)
                        except ParseError, err:
                            raise DefineException.ConfigurationDefineException(self.infos["SOURCES_PATH"] + "/" + configuration, err.line_number, err.line)
                        if edit:
                            try:
                                path = self.infos["PROJECT_NAME"]
                                directory = self.infos["PROJECT_PATH"]
                                user_configuration = loadConfigurationInfos(directory + "/" + configuration.replace("bertos", path))
                                configuration_info[configuration] = updateConfigurationValues(configuration_info[configuration], user_configuration)
                            except ParseError, err:
                                raise DefineException.ConfigurationDefineException(directory + "/" + configuration.replace("bertos", path))
                module_info_dict.update(module_dict)
                configuration_info_dict.update(configuration_info)
                if to_be_parsed:
                    try:
                        list_dict = loadDefineLists(comment_list[1:])
                        list_info_dict.update(list_dict)
                    except ParseError, err:
                        raise DefineException.EnumDefineException(path, err.line_number, err.line)
        for tag in self.infos["CPU_INFOS"]["CPU_TAGS"]:
            for filename, path in self.findDefinitions("*_" + tag + ".h"):
                comment_list = getCommentList(open(path + "/" + filename, "r").read())
                list_info_dict.update(loadDefineLists(comment_list))
        self.infos["MODULES"] = module_info_dict
        self.infos["LISTS"] = list_info_dict
        self.infos["CONFIGURATIONS"] = configuration_info_dict
        self.infos["FILES"] = file_dict

    def loadSourceTree(self):
        """
        Index BeRTOS source and load it in memory.
        """
        # Index only the SOURCES_PATH/bertos content
        bertos_sources_dir = os.path.join(self.info("SOURCES_PATH"), 'bertos')
        file_dict = {}
        if os.path.exists(bertos_sources_dir):
            for element in os.walk(bertos_sources_dir):
                for f in element[2]:
                    file_dict[f] = file_dict.get(f, []) + [element[0]]
        self.infos["FILE_DICT"] = file_dict

    def reloadCpuInfo(self):
        for cpu_info in self.getCpuInfos():
            if cpu_info["CPU_NAME"] == self.infos["CPU_NAME"]:
                self.infos["CPU_INFOS"] = cpu_info

    #-------------------------------------------------------------------------#

    def setInfo(self, key, value):
        """
        Store the given value with the name key.
        """
        self.infos[key] = value

    def info(self, key, default=None):
        """
        Retrieve the value associated with the name key.
        """
        if key in self.infos:
            return copy.deepcopy(self.infos[key])
        return default

    def getCpuInfos(self):
        cpuInfos = []
        for definition in self.findDefinitions(const.CPU_DEFINITION):
            cpuInfos.append(getInfos(definition))
        return cpuInfos

    def searchFiles(self, filename):
        file_dict = self.infos["FILE_DICT"]
        return [(filename, dirname) for dirname in file_dict.get(filename, [])]

    def findDefinitions(self, ftype):
        # Maintain a cache for every scanned SOURCES_PATH
        definitions_dict = self._cached_queries.get(self.infos["SOURCES_PATH"], {})
        definitions = definitions_dict.get(ftype, None)
        if definitions is not None:
            return definitions
        file_dict = self.infos["FILE_DICT"]
        definitions = []
        for filename in file_dict:
            if fnmatch.fnmatch(filename, ftype):
                definitions += [(filename, dirname) for dirname in file_dict.get(filename, [])]

        # If no cache for the current SOURCES_PATH create an empty one
        if not definitions_dict:
            self._cached_queries[self.infos["SOURCES_PATH"]] = {}
        # Fill the empty cache with the result
        self._cached_queries[self.infos["SOURCES_PATH"]][ftype] = definitions
        return definitions

    def setEnabledModules(self, enabled_modules):
        modules = self.infos["MODULES"]
        files = {}
        for module, information in modules.items():
            information["enabled"] = module in enabled_modules
            if information["enabled"]:
                for dependency in information["depends"]:
                    if not dependency in modules:
                        files[dependency] = files.get(dependency, 0) + 1
        self.infos["MODULES"] = modules
        self.infos["FILES"] = files
            
    def __repr__(self):
        return repr(self.infos)
