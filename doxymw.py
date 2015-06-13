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
from doxymwpage import DoxyMWException, DoxygenHTMLPage, CategoryPage, BotUserPage, TransclusionPage

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
                        doxymwglobal.msg(doxymwglobal.warning, "Parameter " + warn + " is not set to " + warnParams[warn])
                
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
                for regex, type in params["doxygen_filePrefixes"].items():
                    if re.search(regex, fileName):
                        fileDoxyType = type
            
            #Filter out the html files without type
            if fileDoxyType == None:
                print(".", end="", flush=True)
                continue
            
            print("*", end="", flush=True)
            
            #Make the doxygen wiki page object
            page = DoxygenHTMLPage(fileAbsPath, fileTail, fileDoxyType)
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
            if option["debug"] != "doxygen" and option["debug"] != "unsafeUpdate":
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

    #( 4 )Perform all the wiki tasks
    #Make sure we're logged in - Use login.py script
    login.main("-pass:not_the_real_password_replace_this")
    
    #Top level category objects
    docsCategory = DoxygenHTMLPage.globalCategory
    transCategory = TransclusionPage.globalCategory
    transExternCategory = TransclusionPage.globalExternCategory
    
    #Returns a generator that matches all DoxyMWPages (That aren't non-redirect transclusions)
    def DoxyMWPageGenerator():
        #All the doc category documents
        fac = GeneratorFactory()
        #All the doc category documents
        fac.handleArg("-catr:" + docsCategory.title)
        fac.handleArg("-subcatsr:" + docsCategory.title)
        fac.handleArg("-page:" + docsCategory.mwtitle)
        #The transclusion category page
        fac.handleArg("-page:" + transCategory.mwtitle)
        gen1 = fac.getCombinedGenerator()
                
        #Find all the transclusion pages and only select the ones that are just redirects
        #Don't delete any other transclusion pages
        fac = GeneratorFactory()
        fac.handleArg("-catr:" + transCategory.title)
        gen2 = fac.getCombinedGenerator()
        debugFiltered = doxymwglobal.option["printLevel"].value <= doxymwglobal.msgType.debug.value
        gen2 = pagegenerators.RedirectFilterPageGenerator(gen2, no_redirects=False, show_filtered=debugFiltered)
        
        #Combined generator
        gen = pagegenerators.CombinedPageGenerator([gen1, gen2])
        gen = pagegenerators.PreloadingGenerator(gen)
        return gen
    
    #CLEANUP - Cleans up MOST of DoxyMWBot's content from the wiki
    #Note: This deletes all uploaded doxygen docs and any transclusions that are just redirects
    #It will leave all other content alone
    if option["command"] == "cleanup":
        gen = DoxyMWPageGenerator()
        for page in gen:
            try:
                if not page.exists():
                    continue
                page.delete(reason="", prompt=option["interactive"])
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not delete page.")
                continue
        
    #UPDATE - Create/update all the wiki pages, deletes all old/unused pages
    if option["command"] == "update":
        def modifyAPage(gen, data):
            try:
                page = gen.__next__()
                data.updatePage(page)
                return True
            except DoxyMWException as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, str(e))
                return False
            except StopIteration as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "No page in generator")
                return False
        
        #A set where we can retrieve all new items since last getNew call
        class setNewest(set):
            def __init__(self, *args):
                super().__init__(*args)
                self.oldSet = set()
            
            def getNew(self):
                newStuff = self.difference(self.oldSet)
                self.oldSet = self.copy()
                return newStuff
        
        #TODO: Create the bots user page (only if theres aspecific bot account!)
        
        #Categories we need to make
        neededCategories = setNewest()
        neededCategories.add(docsCategory)
        if doxymwglobal.config["mediaWiki_setupTransclusions"]:
            neededCategories.add(transCategory)
            if transExternCategory:
                neededCategories.add(transExternCategory)        
        #Images we need to upload (for shared images between pages)
        neededImages = setNewest()
         
        #Updated Pages
        updatedPages = []
        
        #Create/update all the documentation pages
        for pageData in wikiPages:
            #Create/overwrite the actual documentation page
            gen = pagegenerators.PagesFromTitlesGenerator([pageData.mwtitle])
            if modifyAPage(gen, pageData):
                updatedPages.append(pageData.mwtitle)
                #This page made something, so make sure it's category is made
                cat = CategoryPage(doxymwglobal.config["mediaWiki_docsCategory"] + "_" + pageData.type, parent=docsCategory)
                neededCategories.add(cat)
                    
            #Create the transclusion pages
            if doxymwglobal.config["mediaWiki_setupTransclusions"]:
                transPageData = pageData.getTransclusionPage()
                gen = pagegenerators.PagesFromTitlesGenerator([transPageData.mwtitle])
                if modifyAPage(gen, transPageData):
                    updatedPages.append(transPageData.mwtitle)
                     
            #Upload all images - Use upload.py script
            docsImgCategory = CategoryPage(doxymwglobal.config["mediaWiki_docsCategory"] + "_" + "IMAGE", parent=docsCategory)
            #Can't use union because it returns a set ;_;
            for i in pageData.imgs:
                neededImages.add(i)
            
            #Create all added images
            new = neededImages.getNew()
            for img in new:
                imgPath = doxymwglobal.config["doxygen_tmpPath"] + "/html/" + img
                doxymwglobal.msg(doxymwglobal.msgType.info, imgPath)
                upload.main("-keep", "-noverify", "-ignorewarn", imgPath, "Autogenerated Doxygen Image\n" + "[[" + docsImgCategory.mwtitle + "]]")
                #TODO: REPLACE upload.py! It's shit for using as an automated script
                updatedPages.append("FILE:" + img)
                neededCategories.add(docsImgCategory)
                
            #Create all added categories
            new = neededCategories.getNew()
            for catPageData in new:
                fac = GeneratorFactory()
                fac.handleArg("-page:" + catPageData.mwtitle)
                gen = fac.getCombinedGenerator()
                gen = pagegenerators.PreloadingGenerator(gen)
                if modifyAPage(gen, catPageData):
                    updatedPages.append(catPageData.mwtitle)
                        
            lastCategories = neededCategories.copy()
            
        
        #Delete all old pages
        gen = DoxyMWPageGenerator()
        #Filter out all updated pages
        #Filter requires all strings be regex patterns in a list in a special object based on family name and language
        updatedPages = [re.escape(str) for str in updatedPages]
        updatedPages = { "freespace" : { "en" : updatedPages }}
        gen = pagegenerators.PageTitleFilterPageGenerator(gen, updatedPages)
        for page in gen:
            try:
                page.delete(reason="", prompt=option["interactive"])
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not delete old page.")
                continue
                
        #Uncache all the pages
        """
        gen = DoxyMWPageGenerator()
        for page in gen:
            try:
                if not page.exists():
                    continue
                page.purge
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " purged")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not purge page.")
                continue
        """
        
    #( 5 ) We're done!
    doxymwglobal.msg(doxymwglobal.msgType.info, "Done")

if __name__ == '__main__':
    main()