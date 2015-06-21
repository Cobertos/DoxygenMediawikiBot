#A python bot sitting atop PyWikibot and Doxygen to automatically
#add doxygen docs to a wiki for your documentation pleasure

#The main goal of this is to take the power and placement of doxygen docs
#and combine it with the flexibility and remoteness of a wiki

import re
import os
import sys
import subprocess
import errno

import pywikibot

import doxymwglobal
from doxymwsite import DoxyMWSite
from doxymwpage import DoxygenHTMLPage

#Calls doxygen using a config file and outputs everything to a temporary path
def generateDoxygenHTMLDocs():
    #Try the config file
    with open(doxymwglobal.config["doxygen_configPath"]) as fp:
        configLines = fp.readlines()
        fp.seek(0)
        config = fp.read()
        
        #Parameters we must force to generate proper, small, output
        params = {}
        params["doxygen_paramsForce"] = {
        #Output file format and location
        #Critical
        "OUTPUT_DIRECTORY"       : "\"" + doxymwglobal.config["doxygen_tmpPath"] + "\"",
        "GENERATE_HTML"          : "YES",
        "HTML_OUTPUT"            : "html",
        "HTML_FILE_EXTENSION"    : ".html",
        "HIDE_COMPOUND_REFERENCE": "YES", #Cleaner titles

        #Disabling specific HTML sections
        #Possibly critical, makes HTML easier to work with
        "DISABLE_INDEX"          : "YES",
        "SEARCHENGINE"           : "NO",

        #Turn off other generation
        #Not critical but wanted
        #Extra HTML
        "GENERATE_DOCSET"        : "NO",
        "GENERATE_HTMLHELP"      : "NO",
        "GENERATE_QHP"           : "NO",
        "GENERATE_ECLIPSEHELP"   : "NO",
        "GENERATE_TREEVIEW"      : "NO",

        #Other generations
        "GENERATE_LATEX"         : "NO",
        "GENERATE_RTF"           : "NO",
        "GENERATE_XML"           : "NO",
        "GENERATE_DOCBOOK"       : "NO",
        "GENERATE_AUTOGEN_DEF"   : "NO",
        "GENERATE_PERLMOD"       : "NO"
        }

        #Parameters we warn about but do not enforce
        params["doxygen_paramsWarn"] = {
        "CASE_SENSE_NAMES"       : "NO" #MediaWiki doesn't support case sensitivity in title names
        }
        
        
        #Read each line for params to warn about
        warnParams = params["doxygen_paramsWarn"]
        for line in configLines:
            #Comments
            if line[0] == "#":
                continue
            
            match = re.match('\s*(\S+)\s*=\s+(\S*)', line)
            if match:
                k, v = match.group(0,1)
                
                #Warn about specific parameters
                for warn in warnParams.keys():
                    if k == warn and v != warnParams[warn]:
                        doxymwglobal.msg(doxymwglobal.warning, "Doxygen config has parameter " + warn + " not set to " + warnParams[warn] + " which may cause problems.")
                
        #Append the force tags to the end (overwrite the other values)
        forceParams = params["doxygen_paramsForce"]
        for force in forceParams.keys():
            config += "\n" + force + " = " + forceParams[force]
        
        #Call doxygen, piping the config to it
        with subprocess.Popen([doxymwglobal.config["doxygen_binaryPath"] + "/doxygen.exe", "-"], stdin=subprocess.PIPE, universal_newlines=True) as proc:
            proc.communicate(input=config, timeout=20)
            
        #Return after finished

#Reads the doxygen documents at the specified path and returns a list of wikiPages
def readDoxygenHTMLDocs():
    #List of all the actual wiki pages
    wikiPages = []
    
    #Doxygen generates all it's files with prefixes by type
    #This is not an exhaustive list, some configuration patterns have not been tested
    #Files, prefix "_"
    #Interfaces, prefix "interface_"
    #Namespaces, prefix "namespace_"
    #Classes, prefix "class_"
    #Members lists, suffix "-members"
    params = {}
    params["doxygen_filePrefixes"] = {
        "-members$" : "MEMBERS", #Match members lists first
        "^_" : "FILE",
        "^namespace_" : "NAMESPACE",
        "^class_" : "CLASS",
        "^interface_" : "INTERFACE"
    }

    #Other files we want (useful and don't provide redundancies to MediaWiki functionality)
    #Class hierarchy, hierarchy.html
    params["doxygen_otherFiles"] = [
        "hierarchy"
    ]
    
    for root, dirs, files in os.walk(doxymwglobal.config["doxygen_tmpPath"] + "/html"):
        for file in files:
            #Get all the file info
            fileAbs = os.path.abspath(root + "\\" + file)
            fileAbsPath, t = os.path.split(fileAbs)
            fileRel = "./" + os.path.relpath(fileAbs, doxymwglobal.config["doxygen_tmpPath"])
            fileRelPath, fileTail = os.path.split(fileRel)
            fileName, fileExt = os.path.splitext(fileTail)
            
            #Filter out by extension
            if fileExt != ".html":
                continue
       
            #Check special files and type
            fileDoxyType = None
            #Special ("other") files
            for other in params["doxygen_otherFiles"]:
                if fileName == other:
                    fileDoxyType = "OTHER"
                    break
            
            #Check type
            if not fileDoxyType:
                for regex, type in params["doxygen_filePrefixes"].items():
                    if re.search(regex, fileName):
                        fileDoxyType = type
                        break
            
            #Filter out the html files without type
            if fileDoxyType == None:
                continue
            
            
            #Make the doxygen wiki page object
            page = DoxygenHTMLPage(fileAbsPath, fileTail, fileDoxyType)
            wikiPages.append(page)
    return wikiPages
    
def main():
    #( 0 ) Get opts
    from doxymwglobal import option #Default opts
    
    #Argv[1] must be a command
    if len(sys.argv) < 2:
        doxymwglobal.msg(doxymwglobal.msgType.error, "Too few arguments given", usage=True)
        
    option["command"] = sys.argv[1]
    
    if option["command"] != "cleanup" and option["command"] != "update":
        doxymwglobal.msg(doxymwglobal.msgType.error, "Invalid command specified", usage=True)
    
    #Argv[2:] must be other flags
    for arg in sys.argv[2:]:
        if arg == "-i" or arg == "--interactive":
            option["interactive"] = True
        elif arg == "-w" or arg == "--warnIsError":
            option["warnIsError"] = True
        elif arg == "-h" or arg == "--help":
            printHelp()
            return
        elif arg.find("-d:") == 0 or arg.find("--debug:") == 0:
            whichDebug = arg.split(":")[1]
            if whichDebug != "doxygen" and whichDebug != "unsafeUpdate" and whichDebug != "whichDelete":
                doxymwglobal.msg(doxymwglobal.msgType.error, "Invalid debug specified " + whichDebug, usage=True)
            else:
                option["debug"].append(whichDebug)
            
        elif arg.find("-p:") == 0 or arg.find("--printLevel:") == 0:
            printLevel = arg.split(":")[1]
            try:
                #Try it as an int
                printLevelInt = int(printLevel)
                option["printLevel"] = doxymwglobal.msgType(printLevelInt)
            except ValueError:
                try:
                    #Try it as a string of the MsgType enum
                    option["printLevel"] = doxymwglobal.msgType[printLevel.lower()]
                except KeyError:
                    doxymwglobal.msg(doxymwglobal.msgType.error, "Invalid printLevel " + printLevel, usage=True)
                    
        else:
            doxymwglobal.msg(doxymwglobal.msgType.error, "Invalid option", usage=True)
    
    #Do the actual operation
    if option["command"] == "update":
        #( 1 ) Generate the doxygen docs
        generateDoxygenHTMLDocs()
        
        #( 2 )Sort through all files and get the ones we want to parse
        wikiPages = readDoxygenHTMLDocs()
        
        #( 3 )Ready the page by getting everything into valid wiki markup
        for page in wikiPages:
            doxymwglobal.msg(doxymwglobal.msgType.info, "Converting " + page.filename)
            page.convert(wikiPages)
        
        #Debug the first portion, outputs everything to an html file
        if "doxygen" in option["debug"]:
            debugPath = doxymwglobal.debugPath()
            for page in wikiPages:
                doxymwglobal.msg(doxymwglobal.msgType.debug, "Debug output " + page.filename)
                fp = open(debugPath + "/" + page.filename, 'w', errors="replace")
                strr = page.mwtitle+"<br><br>"+page.mwcontents
                fp.write(strr)
            return

    #( 4 )Perform all the wiki tasks
    #Make sure we're logged in
    site = pywikibot.Site()
    
    #Make a site, run the command
    site = DoxyMWSite(site)
    if option["command"] == "cleanup":
        site.cleanup()    
    if option["command"] == "update":
        site.update(wikiPages)
        
    #( 5 ) We're done!
    doxymwglobal.msg(doxymwglobal.msgType.info, "Done")

if __name__ == '__main__':
    main()