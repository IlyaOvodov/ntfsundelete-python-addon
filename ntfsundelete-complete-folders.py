# -*- coding: utf-8 -*-
from collections import defaultdict
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
import re
import json
import traceback
import sys
import os
import time
import shutil
import codecs
import operator


class NTFS_Rescuer():
# 

# preconditions:	
# postconditions:	

    def __init__(self, destfolder):
        self.destfolder = destfolder
        self.checkfolder(destfolder)
    
    def checkfolder(self, destfolder):
        directory = destfolder
        if not os.path.exists(directory):
            os.makedirs(directory)
        
    def load_inodes_to_json(self, inputfile, jsonfile):
        
        inodesdic = {}	# dictionary to keep all the inodes
        pat_inode = re.compile(r'^MFT Record (\d+)')
        fin = open(inputfile, "r", encoding="utf-8")		
        # skip the first two lines
        next(fin)
        next(fin)
        data = fin.readlines()
        # initialize new entry
        content = []	
        
        for line in data:			
            if line == '\n':
                # processing collected entry content
                # find the inode and put it to dictionary
                for cc in content:
                    groupmatch = pat_inode.match(cc)
                    if groupmatch:
                        iid = groupmatch.group(1)
                        int(iid)
                        #print(iid)
                        inodesdic[iid] = content						
                # initialize new entry
                content = []	
            else:
                content.append(line.rstrip())		
        fin.close()
        print(">>> Inodes read in: ", str(len(inodesdic)))
        with codecs.open(jsonfile, 'w', encoding="utf-8") as file:
            json.dump(inodesdic, file)
        print(">>> Inodes transformed into json file.")
        
    def parse_json(self, jsonfile, parsedfile):
        
        patterns = {}
        patterns["recoverrate"] = re.compile(r'^File is (\d+)% recoverable')
        patterns["type"] = re.compile(r'^Type: (.+)')
        patterns["date"] = re.compile(r'^Date: (.+)')
        patterns["name"] = re.compile(r'^Filename: \(0\) (.+)')
        patterns["parent"] = re.compile(r'^Parent: (.+)')
        patterns["datec"] = re.compile(r'^Date C: (.+)')
        patterns["datea"] = re.compile(r'^Date A: (.+)')
        patterns["datem"] = re.compile(r'^Date M: (.+)')
        patterns["dater"] = re.compile(r'^Date R: (.+)')
        patterns["size"] = re.compile(r'^Size alloc: (\d+)')
        
                
        with codecs.open(jsonfile, 'r', encoding="utf-8") as fin:
            inodesdic = json.load(fin)
        for iid in inodesdic:
            newcontent = {}						
            newcontent["recoverrate"] = -1
            newcontent["type"] = ""
            newcontent["date"] = "1901-01-01 23:59" # using string as json serialization puts to string anyway
            newcontent["name"] = ""
            newcontent["parent"] = ""
            newcontent["datec"] = "1901-01-01 23:59"
            newcontent["datea"] = "1901-01-01 23:59"
            newcontent["datem"] = "1901-01-01 23:59"
            newcontent["dater"] = "1901-01-01 23:59"
            newcontent["size"] = -1
            
            for pp in patterns:
                for contentline in inodesdic[iid]:
                #print(contentline)				
                    groupmatch = patterns[pp].match(contentline)
                    if groupmatch:
                        newcontent[pp] = groupmatch.group(1)
                        break
        
            inodesdic[iid] = newcontent
        
        with codecs.open(parsedfile, 'w', encoding="utf-8") as file:
            json.dump(inodesdic, file)
        print(">>> Information parsed and parsed file produced.")

    @dataclass
    class Element:
        iid: int
        name: str
        parent_name: str
        parent_element = None
        
    @dataclass
    class Folder(Element):
        subfolders: list = field(default_factory=list)
        files: list = field(default_factory=list)
        files_size: int = 0
        total_files_count: int = 0
        total_files_size: int = 0

        def update_totals(self, cnt, sz):
            self.total_files_count += cnt
            self.total_files_size += sz
            if self.parent_element is not None:
                self.parent_element.update_totals(cnt, sz)
            
        def set_parent(self, parent, CYCLE_FOLDER):
            if self.parent_element is not None:
                self.parent_element.subfolders = [x for x in self.parent_element.subfolders if x != self]
                self.parent_element.update_totals(-self.total_files_count, -self.total_files_size)

            # check for cycle
            it_parent = parent
            while it_parent is not None:
                if it_parent.iid == self.iid:
                    print(f"cycle for {self.iid}: '{self.name}' -> {parent.iid}: '{parent.name}'")
                    parent = CYCLE_FOLDER
                    break
                it_parent = it_parent.parent_element 
                
            if parent is not None:
                parent.subfolders.append(self)
                parent.update_totals(self.total_files_count, self.total_files_size)
                self.parent_name = parent.name
            else:
                self.parent_name = None 
            self.parent_element = parent
    
    @dataclass
    class File(Element):
        date: str
        datec: str
        datea: str
        datem: str
        dater: str
        size: str
        type: str  # not used
        recoverrate: str  # not used
        parent: str  # not used

        def set_parent(self, parent, CYCLE_FOLDER):
            if self.parent_element is not None:
                self.parent_element.files = [x for x in self.parent_element.files if x != self]
                self.parent_element.files_size -= int(self.size)
                self.parent_element.update_totals(-1, -int(self.size))
            self.parent_element = parent
            if parent is not None:
                parent.files.append(self)
                parent.files_size += int(self.size)
                self.parent_element.update_totals(1, int(self.size))
                self.parent_name = parent.name
            else:
                self.parent_name = None 
 
    def create_structure(self, parsedfile):
        with codecs.open(parsedfile, 'r', encoding="utf-8") as fin:
            inodesdic = json.load(fin)

        ROOT_FOLDER_IID = -1
        ORPHAN_FOLDER_IID = -2
        CYCLE_FOLDER_IID = -3
        ROOT_FOLDER = self.Folder(iid=ROOT_FOLDER_IID, name='___ROOT_FOLDER___', parent_name=None)
        ORPHAN_FOLDER = self.Folder(iid=ORPHAN_FOLDER_IID, name='___ORPHAN_FOLDER___', parent_name=None)
        CYCLE_FOLDER = self.Folder(iid=CYCLE_FOLDER_IID, name='___CYCLE_FOLDER___', parent_name=None)
        SPEC_FOLDERS = (CYCLE_FOLDER, ROOT_FOLDER, ORPHAN_FOLDER)
    
        iid_to_folder = dict({ f.iid: f for f in SPEC_FOLDERS})
        folder_name_to_folders = defaultdict(list, {f.name: [f] for f in SPEC_FOLDERS})

        files = []
        file_size_sum = 0 
        for iid, rec in inodesdic.items():
            iid = int(iid)
            if rec["type"] == "Directory":
                folder = self.Folder(iid=iid, name=rec["name"],  parent_name=rec["parent"])
                assert iid not in iid_to_folder, iid
                iid_to_folder[iid] = folder
                folder_name_to_folders[folder.name].append(folder)
            else:
                assert rec["type"] == "File", rec["type"]
                if rec["recoverrate"] == "100":
                    file = self.File(iid=iid, parent_name=rec["parent"], **rec)
                    files.append(file)
                    file_size_sum += int(int(file.size))
        print(f"Total {len(iid_to_folder)} folders, {len(files)} files using {file_size_sum/1024/1024} MB")
    
        orphan_iid = -1000
        def setup_parent(obj: self.Element):
            if obj in SPEC_FOLDERS:
                return            
            if obj.parent_element is not None:
                if obj.parent_element in SPEC_FOLDERS:
                    return
                assert False, f"obj. already have parent: {obj.parent_element.name}"
                
            possible_parents = folder_name_to_folders[obj.parent_name]
            if len(possible_parents) == 0:
                nonlocal orphan_iid
                if obj.parent_name is None:
                    assert False
                parent = self.Folder(iid=orphan_iid, name=obj.parent_name,  parent_name=ORPHAN_FOLDER.name)
                parent.set_parent(ORPHAN_FOLDER, CYCLE_FOLDER)
                iid_to_folder[orphan_iid] = parent
                folder_name_to_folders[obj.parent_name].append(parent)
                orphan_iid -= 1
            elif len(possible_parents) == 1:
                parent = possible_parents[0]
            else:
                # resolve ambiguity: take candidate with smaller but nearest inode of the potential parents
                possible_parents = sorted(possible_parents, key=lambda f: f.iid)
                parent = None
                for p in possible_parents:						
                    if parent is not None and p.iid >= obj.iid:
                        break
                    if p != obj:
                        parent = p
            if parent == obj:
                parent = CYCLE_FOLDER
            obj.set_parent(parent, CYCLE_FOLDER)

        # setup parents
        for f in files:
            setup_parent(f)
        for f in list(iid_to_folder.values()): # items are added to original dict in ineration
            setup_parent(f)

        # remove empty folders
        def check_and_erase(f):
            if len(f.subfolders) == 0 and len(f.files) == 0:
                assert f.total_files_count == 0 
                assert f.total_files_size == 0
                assert f.files_size == 0
                p = f.parent_element
                f.set_parent(None, CYCLE_FOLDER)  # remove from parent's subfolders
                iid_to_folder.pop(f.iid)
                if p is not None:
                    check_and_erase(p)
                 
            
        all_ids = list(iid_to_folder.keys())
        for id in all_ids:
            f = iid_to_folder.get(id)
            if f is not None:
                check_and_erase(f)
   
        # validate                
        #   cycles
        for f in iid_to_folder.values():
            start_f = f
            visited = set()
            while f not in SPEC_FOLDERS:
                if f.parent_element.iid in visited:
                    print(f"cycle for {f.iid}: '{f.name}' -> {f.parent_element.iid}: '{f.parent_element.name}'")
                    assert False
                visited.add(f.iid)
                f = f.parent_element
        #   roots
        for f in files:
            assert f.parent_element is not None
        for f in iid_to_folder.values():
            if f not in SPEC_FOLDERS:
                assert f.parent_element is not None
        #   relations
        for f in iid_to_folder.values():
            for s in f.subfolders:
                if s.parent_element != f:
                    assert False, f"wrong tree"

        # replace incorrect names
        def update_names(f_list):
            repeats = defaultdict(int)
            for f in f_list:
                if f.name == "":
                    f.name = f"___inode_{f.iid}___"
            for f in f_list:
                while True:
                    n = repeats[f.name]
                    repeats[f.name] += 1
                    if n == 0:
                        break
                    f.name = f"{f.name}___{n+1}"
                    
        def update_lists(f):
            for ff in f.subfolders:
                if ff.name == ".":
                    ff.name = "___.___"
                if ff.name == "<non-determined>":
                    ff.name = "___non-determined___"
            update_names(f.subfolders)
            f.files = sorted(f.files, reverse=True, key=lambda x: x.date)
            update_names(f.files)
            for ff in f.subfolders:
                update_lists(ff)
        
        for f in SPEC_FOLDERS:
            update_lists(f)
        
        return SPEC_FOLDERS
    
    def print_folders(self, root_folders, depth=None):
        # print structure
        i = 0
        seen = set()
        def print_structure(f, margin = 0):
            if depth and margin >= depth:
                return
            nonlocal i
            nonlocal seen
            if f.iid in seen:
                assert False
            seen.add(f.iid)
            i += 1 
            print(i, "  " * margin, f.iid, f"'{f.name}'", len(f.files), f.files_size / 1024 / 1024, f.total_files_count, f.total_files_size / 1024 / 1024)
            for ff in sorted(f.subfolders, key=lambda x:x.name):
                print_structure(ff, margin+1)

        for f in root_folders:
            print_structure(f)

    def create_folders(self, root_folders, destfolder):
        destfolder = Path(destfolder)
        for f in root_folders:
            fld_full_path = destfolder / f.name
            fld_full_path.mkdir(parents=False, exist_ok=False)
            self.create_folders(f.subfolders, fld_full_path)
            
    def create_restore_script(self, sourcedevice, root_folders, destfolder, target_sh):

        total_cnt = 0
        total_sz = 0
        for f in root_folders:
            total_cnt += f.total_files_count
            total_sz += f.total_files_size

        processed_cnt = 0
        processed_sz = 0

        def write_restore_cmd(outfile, sourcedevice, f_rec, destfolder):
            nonlocal processed_cnt
            nonlocal processed_sz
            processed_cnt += 1
            processed_sz += int(f_rec.size)
            outputstring = f'echo "file {processed_cnt}/{total_cnt} ({100*processed_cnt/total_cnt:.2f}%) size {processed_sz}/{total_sz} ({100*processed_sz/total_sz:.2f}%) file {destfolder / f_rec.name}"'
            outfile.write(outputstring + "\n")
            outputstring = f'ntfsundelete {sourcedevice} -u -i {f_rec.iid} -o "{f_rec.name}" -d "{destfolder}"' # && echo \"" + fullpath + "\" >> ./success.txt || echo \"" + fullpath + "\" >> ./failed.txt'
            outfile.write(outputstring + "\n")

        def process_folder(outfile, sourcedevice, folder, destfolder):
            destfolder = Path(destfolder)
            fld_full_path = destfolder / folder.name
            outputstring = f'mkdir "{fld_full_path}"'
            outfile.write("\n\n" + outputstring + "\n")
            for f_rec in folder.files:
                write_restore_cmd(outfile, sourcedevice, f_rec, fld_full_path)
            for subfolder in folder.subfolders:
                process_folder(outfile, sourcedevice, subfolder, fld_full_path)            
        
        with codecs.open(target_sh, 'w', encoding="utf-8") as outfile:
            outfile.write("#!/bin/bash\n")
            for folder in root_folders:
                process_folder(outfile, sourcedevice, folder, destfolder)

        
try:
    
    sourcedevice="/dev/md1"
    destfolder = '/mnt/nvme/recover2'
    inputfile = '/mnt/nvme/scan2.txt'
    jsonfile = '/mnt/nvme/inodes2.json'
    parsedfile = '/mnt/nvme/inodes-filtered2.json'
    target_sh = '/mnt/nvme/restore.sh'
    
    # runtime action
    Rescuer = NTFS_Rescuer(destfolder)
    #Rescuer.load_inodes_to_json(inputfile, jsonfile)
    #Rescuer.parse_json(jsonfile, parsedfile)
    root_folders = Rescuer.create_structure(parsedfile)
    Rescuer.print_folders(root_folders, depth=2)
    #Rescuer.create_folders(root_folders, destfolder)
    Rescuer.create_restore_script(sourcedevice, root_folders, destfolder, target_sh)

    

except:
    print(traceback.format_exc())