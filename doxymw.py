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

import doxymwglobal
from doxymwpage import DoxygenMediaWikiPage

#Calls doxygen using a config file and outputs everything to a temporary path
def generateDoxygenHTMLDocs():
    print(doxymwglobal.config)

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
        "HIDE_COMPOUND_REFERENCE": "YES",

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
    
    for root, dirs, files in os.walk(doxymwglobal.config["doxygen_tmpPath"] + "/html"):
        for file in files:
            #Get all the file info
            fileAbsPath = os.path.abspath(root + "\\" + file)
            fileRelPath = os.path.relpath(fileAbsPath, doxymwglobal.config["doxygen_tmpPath"] + "/html")
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
            page = DoxygenMediaWikiPage(fileAbsPath, fileTail, fileDoxyType)
            wikiPages.append(page)
    print("")
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
            option["debug"] = arg.split(":")[1]
            if option["debug"] != "doxygen":
                doxymwglobal.msg(doxymwglobal.msgType.error, "Invalid debug specified " + option["debug"], usage=True)
            
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
        if option["debug"] == "doxygen":
            debugPath = doxymwglobal.config["doxygen_tmpPath"] + "/debug"
            try:
                os.mkdir(debugPath)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise #Rethrow if not a folder already exists error
            for page in wikiPages:
                doxymwglobal.msg(doxymwglobal.msgType.info, "Debug output " + page.filename)
                fp = open(debugPath + "/" + page.filename, 'w', errors="replace")
                strr = page.mwtitle+"<br><br>"+page.mwcontents
                fp.write(strr)
            return

    #( 4 )Create necessary pages on the wiki
    #Make sure we're logged in - Use login.py script
    login.main("-pass:not_the_real_password_replace_this")
    
    #First delete anything in the autogenerated categories
    fac = GeneratorFactory()
    fac.handleArg("-catr:" + doxymwglobal.config["mediaWiki_docsCategory"])
    gen = fac.getCombinedGenerator()
    gen = pagegenerators.PreloadingGenerator(gen)
    for page in gen:
        try:
            if page.isCategory():
                continue
            else:
                page.delete(reason="", prompt=option["interactive"])
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
            #If we ever go back to this
            #elif page.isImage():
                #page.delete(reason="", prompt=option["interactive"])
            #else:
                #page.get()
                #text = page.text
                #if page.text.find("Doxygen object no longer exists") != -1:
                    #page.delete(reason="", prompt=option["interactive"])
                #else:
                #    page.text = "Doxygen object no longer exists"
                #    # Save the page
                #    page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not delete page.")
            continue
        
    #Now create all the pages
    for pageData in wikiPages:
        
        #Create/overwrite the actual documentation page
        #TODO: We should eventually use a PreloadingPageGenerator (send out bursts of requests?)
        #  and not make a generator one page at a time
        mwTitle = pageData.mwtitle
        gen = pagegenerators.PagesFromTitlesGenerator([mwTitle])
        for page in gen:
            #Whether the page exists or not just create/overwrite it
            try:
                page.text = pageData.mwcontents
                # Save the page
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not create page.")
                continue
                
        
        #Create/overwrite category (add it to main category)
        mwCategory = doxymwglobal.config["mediaWiki_docsCategory"] + "_" + pageData.type
        gen = pagegenerators.PagesFromTitlesGenerator(["Category:" + mwCategory])
        for page in gen:
            if page.exists():
                continue
            try:
                page.text = "[[Category:" + doxymwglobal.config["mediaWiki_docsCategory"] + "]]"
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not create category page.")
                continue
                
        #Create the transclusion pages
        if doxymwglobal.config["mediaWiki_setupTransclusions"]:
            transCategory = ""
            if "mediaWiki_transclusionCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionCategory"] != "":
                transCategory = "Category:" + doxymwglobal.config["mediaWiki_transclusionCategory"]   
            
            #Create the transclusion page
            gen = pagegenerators.PagesFromTitlesGenerator([pageData.mwtranstitle])
            for page in gen:
                putText = ""
                
                #If the page doesn't exist or is old redirect, make it as a blank redirect
                if not page.exists() or page.isRedirectPage():
                    putText = pageData.mwtranscontents
                    
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
                        doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not create transclusions page.")
                        continue
        
        #Check image category page
        mwImgCategory = doxymwglobal.config["mediaWiki_docsCategory"] + "_" + "IMAGE"
        gen = pagegenerators.PagesFromTitlesGenerator(["Category:" + mwImgCategory])
        for page in gen:
            if page.exists():
                continue
            try:
                page.text = "[[Category:" + doxymwglobal.config["mediaWiki_docsCategory"] + "]]"
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not create category page.")
                continue
                        
        #Upload all images - Use upload.py script
        mwImgCategory = "[[Category:" + doxymwglobal.config["mediaWiki_docsCategory"] + "_" + "IMAGE" + "]]"
        for img in pageData.imgs:
            doxymwglobal.msg(doxymwglobal.msgType.info, img)
            upload.main("-keep", doxymwglobal.config["doxygen_tmpPath"] + "/html/" + img, "Autogenerated Doxygen Image\n" + mwImgCategory)
        
    #( 5 ) We're done!
    doxymwglobal.msg(doxymwglobal.msgType.info, "Done")

if __name__ == '__main__':
    main()