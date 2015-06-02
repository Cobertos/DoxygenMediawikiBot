#A python bot sitting atop PyWikibot and Doxygen to automatically
#add doxygen docs to a wiki for your documentation pleasure

#The main goal of this is to take the power and placement of doxygen docs
#and combine it with the flexibility and remoteness of a wiki.

#TODO:
#fix all the TODOS in the code
#implement everything
#Clone doxygen's easy navigation with some templates for mediawiki
#Special styles for the doxygen wikipedia docs
#Make sure to include links and logos to doxygen so we properly attribute them

import os
import subprocess
from html.parser import HTMLParser

#A HTML Parser that simply keeps track of our current position with a stack
#TODO: Make or use more powerful HTML Parser. The current functionality
#  the current needs but is definitely a bit unforgiving when replacing tags
class HTMLParserStackException(Exception):
    pass
class HTMLTagIdentifier(object):
    def __init__(self, tag, attrs):
        self.tag = tag
        #Convert tuple list to dictionary
        self.attrs = {}
        for item in attrs:
            self.attrs[item[0]] = item[1]

    def getIdentStr(self):
        #Build a full tag identifier like CSS
        #Only class attribute currently needs support
        fullTag = self.tag
        if "class" in self.attrs:
            fullTag += "." + self.attrs["class"]
        
        return fullTag
class HTMLParserStack(HTMLParser):        
    def __init__(self):
        super().__init__()
        self.tagStack = []
    
    def handle_starttag(self, tag, attrs):
        #Keep track of tags on the stack
        newTag = HTMLTagIdentifier(tag, attrs)
        self.tagStack.append(newTag)
    
    def handle_endtag(self, tag):
        #Pop off a tag and compare it with the stack
        pastTag = self.tagStack.pop()
        if pastTag.tag != tag:
            #Popped tag does not match the current stack, that's not right...
            #This could be a sign of malformed HTML or something with a <dd> tag (look that up #TODO:)
            #Keep popping until we find the first correct tag, if it was just an extra tag or a few on the stack we're good
            #If not it'll fuck up the stack so when we pop later we'll eventually end up popping the entire stack looking for the next tag
            #  and that's where we catch the real malformed HTML error (when a tags are closed in the wrong order or other things)
            print("WARNING: Tag popped doesn't match stack")
            
            #Keep popping until we get the right tag
            #Keep original for error reporting
            origTagStack = self.tagStack[:]
            origTagStack.append(pastTag)
            while len(self.tagStack) > 0:
                pastTag = self.tagStack.pop()
                if pastTag.tag == tag:
                    break
                
            if(len(self.tagStack) <= 0):
                #We never found a matching tag to pop, uh oh
                #Raise an error
                str=[]
                for tag in origTagStack:
                    str.append(tag.getIdentStr())
                
                raise HTMLParserStackException("Invalid HTML encountered, improper tag closure at " + " > ".join(str))
    
    #Test the tag stack
    def testStack(self, test):
        if len(self.tagStack) != len(test):
            return False
        
        for i in range(len(self.tagStack)):
            if self.tagStack[i].getIdentStr() != test[i]:
                return False
        return True

#A HTMLParser that extracts portions of a doxygen HTML file
#The data attribute is of the most use to us
#It comes containing a dictionary of strings to HTML data
#These strings are:
# + title: The title of the Doxygen file
# + contents: The body of the Doxygen file
class DoxygenHTMLExtractor(HTMLParserStack):
    def __init__(self):
        super().__init__()
        
        self.data = {}
        self.captureDataAs = None
        self.captureDataUntil = None
        
    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        self.startTag(tag, attrs)
    
    def handle_startendtag(self, tag, attrs):
        self.startTag(tag, attrs)
    
    def startTag(self, tag, attrs):
        #Recording data
        if self.captureDataAs != None:
            self.data[self.captureDataAs] += self.get_starttag_text()
            return
            
        #Look for specific tags to capture data from
        titleStack = ["html", "body", "div.header", "div.headertitle", "div.title"]
        contentsStack = ["html", "body", "div.contents"]
        if self.testStack(titleStack):
            self.captureDataAs = "title"
            self.captureDataUntil = titleStack
            self.data[self.captureDataAs] = ""
        elif self.testStack(contentsStack):
            self.captureDataAs = "contents"
            self.captureDataUntil = contentsStack
            self.data[self.captureDataAs] = ""
    
    def handle_endtag(self, tag):
        #If we're back at the same tagStack, stop capturing data
        if self.captureDataAs != None:
            if self.testStack(self.captureDataUntil):
                self.captureDataAs = None
                self.captureDataUntil = None
        
        #Recording data
        if self.captureDataAs != None:        
            self.data[self.captureDataAs] += "</" + tag + ">"
        
        super().handle_endtag(tag)
    
    def handle_data(self, data):
        #Recording data
        if self.captureDataAs != None:
            self.data[self.captureDataAs] += data
            return

#A HTMLParser that replaces all HTML with wiki compatible HTML
#Two attributes are of most use to us
#data contains all of the HTML originally fed to it with modifications for the wiki
#imgs contains all the image files that were identified that need to be uploaded to the wiki
class DoxygenHTMLReplacer(HTMLParser):
    def __init__(self, wikiPages):
        super().__init__()
        
        self.wikiPages = wikiPages #Allows us to change links with other wiki pages
        self.data = ""
        self.imgs = []
        
        #TODO: Convert lastTag over to either HTMLParserStack (add more testing functionality) or
        #  get a more powerful HTML parser
        self.lastTag = None
    def handle_starttag(self, tag, attrs):
        self.lastTag = tag
        self.startTag(tag, attrs)
    
    def handle_startendtag(self, tag, attrs):
        self.startTag(tag, attrs)
    
    def startTag(self, tag, attrs):
        #Output of doxygen
        #http://www.stack.nl/~dimitri/doxygen/manual/htmlcmds.html

        #Accepted by mediawiki
        #http://meta.wikimedia.org/wiki/Help:HTML_in_wikitext

        #Output from doxygen and not supported by mediawiki
        #We must convert these
        #<a href="...">
        #<a name="...">
        #<img src="..." ...>
        newTag = HTMLTagIdentifier(tag, attrs)
        
        if newTag.tag == "a":
            #TODO: Somehow add the data of a into the alternative link text section
            self.data += "[["
            if "href" in newTag.attrs:
                href = newTag.attrs["href"]
                hashPos = href.rfind("#")
                fragment = ""
                if hashPos != -1:
                    fragment = href[hashPos:]
                    link = href[:hashPos]
                else:
                    link = href
                
                foundMatch = False
                for page in self.wikiPages:
                    if link == page.filename:
                        foundMatch = True
                        link = page.title
                        break
                
                if not foundMatch:
                    print("WARNING: Couldn't find suitable match for link " + link)
                else:
                    self.data += "[[" + link + fragment + "]]"
            if "name" in newTag.attrs:
                self.data += "<span id=\"" + newTag.attrs["name"] + "\"></span>" #Named anchors in MediaWiki just use the id
            
        elif newTag.tag == "img":
            #TODO: Pic how we're going to style this on the wiki, just uses default
            self.data += "[[File:" + newTag.attrs["src"] + "]]"
            #Make a note of the image
            self.imgs.append(newTag.attrs["src"])
        
        #Not a tag we need to convert
        else:
            self.data += self.get_starttag_text()
    
    def handle_endtag(self, tag):
        #Not a tag we need to convert
        #MW links and imgs are handled in the other handler, no output needed
        if tag != "a" and tag != "img":
            self.data += "</" + tag + ">"
        
    def handle_data(self, data):
        if self.lastTag != "a" or self.lastTag != "img":
            self.data += data

class DoxygenWikiPage(object):
    def __init__(self):
        #About the file this page came from (every file is a page)
        self.filepath = None
        self.filename = None
        
        #About the page itself
        self.type = None
        self.title = None
        self.contents = None
    
            
def main():
    #Options:
    options = {}
    
    #Path to doxygen
    options["doxygen_path"] = "C:/Users/PeterF/Desktop/DoxygenWikibot/html"
    
    #Types of files we're interested in
    #Files that describe:
    #Files, prefix "_"
    #Interfaces, prefix "interface_"
    #Namespaces, prefix "namespace_"
    #Classes, prefix "class_"
    options["doxygen_filePrefixes"] = {
        "_" : "FILE",
        "namespace_" : "NAMESPACE",
        "class_" : "CLASS",
        "interface_" : "INTERFACE"
    }
    
    #Other files we want (useful and don't provide redundancies to media wiki functionality)
    #Class hierarchy, hierarchy.html
    options["doxygen_otherFiles"] = [
        "hierarchy"
    ]
    
    #Media wiki stuff
    options["mediaWiki_separationName"] = "DoxygenDocs" #The category or namespace name to use for the doxygen docs
    options["mediaWiki_useCustomNamespace"] = False #TODO: (not imeplemented) Whether to use a custom namespace or just a category for all of the doxygen documents


    #( 1 ) Generate the doxygen docs
    ##doxygenPath = "C:\Program Files\doxygen"
    #Take the specified configure file
    #Make sure that the configure file has specifics including
    #
    #
    #
    #
    ##subprocess.call(doxygenPath + "\bin\doxygen.exe", "configure")

    #( 2 )Sort through all files and get the ones we want to parse
    #List of all the actual wiki pages
    wikiPages = []
    
    for root, dirs, files in os.walk(options["doxygen_path"]): #TODO: Replace with option
        for file in files:
            #Get all the file info
            fileAbsPath = os.path.abspath(root + "\\" + file)
            fileRelPath = os.path.relpath(fileAbsPath, options["doxygen_path"])
            filePath, fileTail = os.path.split(fileRelPath)
            fileName, fileExt = os.path.splitext(fileTail)
            
            #Filter out by extension
            if fileExt != ".html":
                print(".", end="", flush=True)
                continue
       
            #Check special files and type
            fileDoxyType = None
            #Special ("other") files
            for other in options["doxygen_otherFiles"]:
                if fileName == other:
                    fileDoxyType = "OTHER"
            
            #Check type
            if not fileDoxyType:
                for prefix in options["doxygen_filePrefixes"]:
                    if fileName[:len(prefix)] == prefix:
                        fileDoxyType = prefix
            
            #Filter out the html files without type
            if fileDoxyType == None:
                print(".", end="", flush=True)
                continue
            
            print("*", end="", flush=True)
            
            #Make the doxygen wiki page object
            page = DoxygenWikiPage()
            page.filepath = fileAbsPath
            page.filename = fileTail
            page.type = fileDoxyType
            
            wikiPages.append(page)
    print("")
    
    #( 3 )Extract the wiki data from each file
    for page in wikiPages:
        print("Parsing " + page.filename)
        fp = open(page.filepath)
    
        #Extract the specific parts of the page for the wiki
        extractor = DoxygenHTMLExtractor()
        extractor.feed(fp.read())
        
        if not "title" in extractor.data or not "contents" in extractor.data:
            print("Not enough information from Doxygen file for wiki page")
            continue
        
        page.title = extractor.data["title"]
        page.contents = extractor.data["contents"]
    
    #( 4 )Ready the page by getting everything into valid wiki markup
    for page in wikiPages:
        print("Converting " + page.filename)
        
        #Translate gathered data into MediaWiki markup
        #Currently we're only worried about "body > div.contents" having translatable markup in it
        translator = DoxygenHTMLReplacer(wikiPages) #Send it wikiPages so it can translate doxygen links to mediaWiki links
        translator.feed(page.contents)
        
        page.contents = translator.data
        page.imgs = translator.imgs
        
        #Add categories to the pages
        page.contents = "[[Category:" + options["mediaWiki_separationName"] + "_" + page.type + "]]"
    
    #( 5 )Create necessary pages on the wiki
    #Make sure we're logged in
    #subprocess.call("python", ".\pwb.py", "login", "-pass:not_the_real_password_replace_this")
    #for page in wikiPages:
        #Check if the category exists
        #If not create it
    
        #Check if the page exists
        #If not create the page
        #Clear the page, set it to contain the content
        
        

    #( 6 ) We're done!
    print("done")

if __name__ == '__main__':
    main()