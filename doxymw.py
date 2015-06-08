#A python bot sitting atop PyWikibot and Doxygen to automatically
#add doxygen docs to a wiki for your documentation pleasure

#The main goal of this is to take the power and placement of doxygen docs
#and combine it with the flexibility and remoteness of a wiki

import re
import os
import sys
import subprocess
import errno

from PyWikibot.scripts import login, upload
from PyWikibot import pywikibot
from PyWikibot.pywikibot import pagegenerators
from PyWikibot.pywikibot.pagegenerators import GeneratorFactory

from doxymwpage import DoxygenMediaWikiPage

#Calls doxygen using a config file and outputs everything to a temporary path
def generateDoxygenHTMLDocs(execPath, configPath, tmpPath):
    #Try the config file
    with open(configPath) as fp:
        configLines = fp.readlines()
        fp.seek(0)
        config = fp.read()
        
        #Parameters we must force to generate proper, small, output
        params = {}
        params["doxygen_paramsForce"] = {
        #Output file format and location
        #Critical
        "OUTPUT_DIRECTORY"       : "\"" + tmpPath + "\"",
        "GENERATE_HTML"          : "YES",
        "HTML_OUTPUT"            : "html",
        "HTML_FILE_EXTENSION"    : ".html",

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
                        print("WARNING: Parameter " + warn + " is not set to " + warnParams[warn])
                
        #Append the force tags to the end (overwrite the other values)
        forceParams = params["doxygen_paramsForce"]
        for force in forceParams.keys():
            config += "\n" + force + " = " + forceParams[force]
        
        #Call doxygen, piping the config to it
        with subprocess.Popen([execPath + "/doxygen.exe", "-"], stdin=subprocess.PIPE, universal_newlines=True) as proc:
            proc.communicate(input=config, timeout=20)
            
        #Return after finished

#Reads the doxygen documents at the specified path and returns a list of wikiPages
def readDoxygenHTMLDocs(path):
    #List of all the actual wiki pages
    wikiPages = []
    
    #Doxygen generates all it's files with prefixes by type
    #This is not an exhaustive list, some configuration patterns have not been tested
    #Files, prefix "_"
    #Interfaces, prefix "interface_"
    #Namespaces, prefix "namespace_"
    #Classes, prefix "class_"
    params = {}
    params["doxygen_filePrefixes"] = {
        "_" : "FILE",
        "namespace_" : "NAMESPACE",
        "class_" : "CLASS",
        "interface_" : "INTERFACE"
    }

    #Other files we want (useful and don't provide redundancies to MediaWiki functionality)
    #Class hierarchy, hierarchy.html
    params["doxygen_otherFiles"] = [
        "hierarchy"
    ]
    
    for root, dirs, files in os.walk(path+"/html"):
        for file in files:
            #Get all the file info
            fileAbsPath = os.path.abspath(root + "\\" + file)
            fileRelPath = os.path.relpath(fileAbsPath, path+"/html")
            filePath, fileTail = os.path.split(fileRelPath)
            fileName, fileExt = os.path.splitext(fileTail)
            
            #Filter out by extension
            if fileExt != ".html":
                print(".", end="", flush=True)
                continue
       
            #Check special files and type
            fileDoxyType = None
            #Special ("other") files
            for other in params["doxygen_otherFiles"]:
                if fileName == other:
                    fileDoxyType = "OTHER"
            
            #Check type
            if not fileDoxyType:
                for prefix in params["doxygen_filePrefixes"]:
                    if fileName[:len(prefix)] == prefix:
                        fileDoxyType = prefix
            
            #Filter out the html files without type
            if fileDoxyType == None:
                print(".", end="", flush=True)
                continue
            
            print("*", end="", flush=True)
            
            #Make the doxygen wiki page object
            page = DoxygenMediaWikiPage()
            page.filepath = fileAbsPath
            page.filename = fileTail
            page.type = fileDoxyType
            
            wikiPages.append(page)
    print("")
    return wikiPages
    
def main():
    
    #( 0 ) Get opts
    options = {}

    #DoxygenMediawikibot
    options["command"] = None
    options["interactive"] = False
    options["debug"] = None
    #options["warnIsError"] = False
    #options["printLevel"] = 0

    #Doxygen related path info
    options["doxygen_binaryPath"] = "C:/Program Files/doxygen/bin"
    options["doxygen_configPath"] = "C:/Users/PeterF/Desktop/DoxygenWikibot/DoxyfileTest" 
    options["doxygen_tmpPath"] = "./tmp" 

    #MediaWiki stuff
    options["mediaWiki_docsCategory"] = "DoxygenDocs" #The category name to use for the doxygen docs, also prefixed onto every name to avoid collisions

    #All pages get another page generated with just the content along with a transclusion
    #The links are properly setup to then always point to the transclusion pages
    #This allows us to put all the autogenerated data in a locked down part of the wiki
    #It also allows quick, dirty, and easy updating of the doxygen docs while allowing users to just configure their
    #own text on the transclusion pages
    options["mediaWiki_setupTransclusions"] = True
    options["mediaWiki_transclusionPrefix"] = "" #Prefix of transclusion, can be empty
    options["mediaWiki_transclusionCategory"] = "CodingDocs" #Category to add all these pages to, can be no category (to turn off)
    
    for arg in sys.argv[1:]:
        if arg == "cleanup":
            options["command"] = "cleanup"
        elif arg == "update":
            options["command"] = "update"
    
        elif arg == "-i" or arg=="-interactive":
            options["interactive"] = True
        elif arg.find("-d:") == 0 or arg.find("--debug:") == 0:
            options["debug"] = arg.split(":")[1]
    
    if not options["command"]:
        print("\n"
        "USAGE: python doxymw.py [command] [opts]\n"
        "command is either\n"
        "update = update some wiki with documentation\n"
        "cleanup = delete all the autogenerated documentation on a wiki\n"
        "\n"
        "opts are\n"
        "-i = interactive\n"
        "-d = debug")
        return
            
    if options["command"] == "update":
        #( 1 ) Generate the doxygen docs
        generateDoxygenHTMLDocs(options["doxygen_binaryPath"], options["doxygen_configPath"], options["doxygen_tmpPath"])
        
        #( 2 )Sort through all files and get the ones we want to parse
        wikiPages = readDoxygenHTMLDocs(options["doxygen_tmpPath"])
        
        #( 3 )Extract the wiki data from each file
        for page in wikiPages:
            print("Parsing " + page.filename)
            page.extract()
        
        #( 4 )Ready the page by getting everything into valid wiki markup
        for page in wikiPages:
            print("Converting " + page.filename)
            page.convert(options["mediaWiki_docsCategory"], wikiPages)
    
        if options["debug"] == "doxygen":
            debugPath = options["doxygen_tmpPath"] + "/debug"
            try:
                os.mkdir(debugPath)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise #Rethrow if not a folder already exists error
            for page in wikiPages:
                print("Debug output " + page.filename)
                fp = open(debugPath + "/" + page.filename, 'w', errors="replace")
                strr = page.title+"\n"+page.contents
                fp.write(strr)
    
    #( 5 )Create necessary pages on the wiki
    #Make sure we're logged in - Use login.py script
    login.main("-pass:not_the_real_password_replace_this")
    
    #First delete anything in the autogenerated categories
    fac = GeneratorFactory()
    fac.handleArg("-catr:" + options["mediaWiki_docsCategory"])
    gen = fac.getCombinedGenerator()
    gen = pagegenerators.PreloadingGenerator(gen)
    for page in gen:
        try:
            if page.isCategory():
                continue
            else:
                page.delete(reason="", prompt=options["interactive"])
                print("Page " + page.title() + " deleted")
            #If we ever go back to this
            #elif page.isImage():
                #page.delete(reason="", prompt=options["interactive"])
            #else:
                #page.get()
                #text = page.text
                #if page.text.find("Doxygen object no longer exists") != -1:
                    #page.delete(reason="", prompt=options["interactive"])
                #else:
                #    page.text = "Doxygen object no longer exists"
                #    # Save the page
                #    page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            print("WARNING: Could not delete page.")
            continue
        
    #Now create all the pages
    for pageData in wikiPages:
        
        #Create/overwrite the actual documentation page
        #TODO: We should eventually use a PreloadingPageGenerator (send out bursts of requests?)
        #  and not make a generator one page at a time
        mwTitle = options["mediaWiki_docsCategory"] + "_" + pageData.title
        gen = pagegenerators.PagesFromTitlesGenerator([mwTitle])
        for page in gen:
            #Whether the page exists or not just create/overwrite it
            try:
                page.text = pageData.contents
                # Save the page
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                print("WARNING: Could not create page.")
                continue
                
        
        #Create/overwrite category (add it to main category)
        mwCategory = options["mediaWiki_docsCategory"] + "_" + pageData.type
        gen = pagegenerators.PagesFromTitlesGenerator(["Category:" + mwCategory])
        for page in gen:
            if page.exists():
                continue
            try:
                page.text = "[[Category:" + options["mediaWiki_docsCategory"] + "]]"
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                print("WARNING: Could not create category page.")
                continue
                
        #Create the transclusion pages
        if options["mediaWiki_setupTransclusions"]:
            transPrefix = ""
            if "mediaWiki_transclusionPrefix" in options and options["mediaWiki_transclusionPrefix"] != "":
                transPrefix = options["mediaWiki_transclusionPrefix"] + " "
                
            transCategory = ""
            if "mediaWiki_transclusionCategory" in options and options["mediaWiki_transclusionCategory"] != "":
                transCategory = "Category:" + options["mediaWiki_transclusionCategory"]   
            
            #Create the transclusion page
            gen = pagegenerators.PagesFromTitlesGenerator([transPrefix + pageData.title])
            for page in gen:
                putText = ""
                
                #If the page doesn't exist or is old redirect, make it as a blank redirect
                if not page.exists() or page.isRedirectPage():
                    putText = "#REDIRECT [[" + mwTitle + "]]\n" + "[[" + transCategory + "]]"
                    
                #If the page does exist, make it a transclusion page
                #This ONLY happens if the page is in our category
                else:
                    #Check if in category
                    hasCat = False
                    if transCategory != "":
                        for cat in page.categories():
                            if cat.title() == transCategory:
                                hasCat = True
                                break
                    else:
                        hasCat = True
                    
                    #If the page is in our category, we can modify it
                    if hasCat:
                        page.get()
                        transTest = "{{:" + mwTitle + "}}"
                        if page.text.find(transTest) == -1:
                            #Append the transclusion to the page, but only if it isn't already there
                            putText = page.text + "\n" + transTest
                
                #If we changed the page, save it
                if putText != "":
                    try:
                        page.text = putText
                        page.save()
                    except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                        print("WARNING: Could not create transclusions page.")
                        continue

        #Upload all images - Use upload.py script
        #TODO: These need to go into the category with everything else
        """for img in page.imgs:
            upload.main("-keep", img, "Autogenerated Doxygen Image")"""
        
    #( 6 ) We're done!
    print("Done")

if __name__ == '__main__':
    main()