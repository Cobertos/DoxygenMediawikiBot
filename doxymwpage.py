#Represents one page in both doxygen and media wiki
import re

from PyWikibot import pywikibot
from bs4 import BeautifulSoup

import doxymwglobal

class DoxyMWException(Exception):
    pass

#Exception when the configuration isn't safe to use
class DoxyMWConfigException(DoxyMWException):
    pass
    
#Function that returns data extracted from Doxygen file for MediaWiki page
#Returns a dictionary with
# + title: The title of the Doxygen file, straight unicode
# + displayTitle: Title of the Doxygen file, with HTML entities
# + contents: The body of the Doxygen file
def DoxygenHTMLExtractor(text):
    soup = BeautifulSoup(text)
    data = {}
    
    def onlyOne(tagList, which):
        if len(tagList) <= 0:
            doxymwglobal.msg(doxymwglobal.msgType.warning, "No " + which + " found")
            return None
        elif len(tagList) > 1:
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Ambiguous " + which)
        return tagList[0]
    
    #Find the title
    select = onlyOne(soup.select("div.header div.title"), "title")
    if not select:
        return None
    data["title"] = select.decode_contents(formatter=None) #Straight unicode
    data["displayTitle"] = select.decode_contents(formatter="html") #With HTML &gt;-type entities
    
    #Find the contents
    select = onlyOne(soup.select("div.contents"), "contents")
    if not select:
        return None
    data["contents"] = select.decode_contents(formatter="html")
    
    #Footer for attribution and date info
    select = onlyOne(soup.select("address.footer"), "footer")
    if not select:
        return None
    data["footer"] = select.decode_contents(formatter="html")
    
    return data

#Function that translates all HTML to MediaWiki markup with the least amount of work
#Returns two objects in a tuple
# + text contains the translated HTML for the wiki
# + imgs contains all identified images that should be uploaded
def DoxygenHTMLConverter(text, wikiPages):
    soup = BeautifulSoup(text)
    imgs = []
    
    #Output of doxygen
    #http://www.stack.nl/~dimitri/doxygen/manual/htmlcmds.html
    #...and <map> tag

    #Accepted by mediawiki
    #http://meta.wikimedia.org/wiki/Help:HTML_in_wikitext

    #Output from doxygen and not supported by mediawiki
    #We must convert these
    #<a href="...">
    #<a name="...">
    #<img src="..." ...>
    #<map>
    
    #Convert <a>s
    for a in soup("a"):
        #A normal link
        if "href" in a.attrs:
            href = a.attrs["href"]
            text = a.string
            #Get link and fragment portions of href
            hashPos = href.rfind("#")
            fragment = ""
            if hashPos != -1:
                fragment = href[hashPos:]
                link = href[:hashPos]
            else:
                link = href
            
            #Compare to list of wiki pages and change if necessary
            internalLink = False
            for page in wikiPages:
                if link == page.filename:
                    internalLink = True
                    link = page.title
                    break
            
            #Make an internal or external link
            if not text:
                newStr = "" #TODO: Handle lack of a.string(We only found tags,like a linked image)
            elif not internalLink:
                newStr = "[" + href + " " + text + "]"
            else:
                newStr = "[[" + link + fragment + "|" + text + "]]"
        
        #A named anchor
        if "name" in a.attrs:
            newStr = soup.new_tag("span")
            newStr.attrs["id"] = a.attrs["name"] #Named anchors in MediaWiki just use the id
            newStr.attrs["style"] = "width:0;height:0;font-size:0;"
    
        a.replace_with(newStr)
        
    #Convert and store <img>s
    for img in soup("img"):
        #File this image for later use
        imgs.append(img.attrs["src"])
        
        #Convert the image
        newStr = "[[File:" + img.attrs["src"] + "]]"
        img.replace_with(newStr)
        
    #Convert <maps>
    #For now just delete them, we'll have to rely on a MW extension for this one later
    for map in soup("map"):
        map.replace_with("") 
        
    return (soup.decode_contents(formatter="html"), imgs)

#An abstract base classes for all other page types
class DoxyMWPage(object):
    @property #Should return the MediaWiki title
    def mwtitle(self):
        raise NotImplementedError("Abstract class property should be implemented")
        
    @property #Should return the MediaWiki page contents
    def mwcontents(self):
        raise NotImplementedError("Abstract class property should be implemented")
    
    #Should check a DoxyMWPage to make sure it's the page we think (safety measure)
    def checkPage(self, page):
        raise NotImplementedError("Abstract class function should be implemented")
    
    #Should update/create a page to conform to the information stored in the object
    def updatePage(self, page):
        #Most classes use this
        if not self.checkPage(page) and not doxymwglobal.option["debug"] == "unsafeUpdate":
            raise DoxyMWException("Page is not the correct page to be edited by this object")
        
        try:
            if page.exists():
                page.get()
                if page.text == self.mwcontents:
                    return #Don't need to make or update
                    
            page.text = self.mwcontents
            page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            raise DoxyMWException("Couldn't create page")
        
        
class CategoryPage(DoxyMWPage):
    def __init__(self, title, parent=None, hidden=True):
        self.title = title
        self.parent = parent
        self.hidden = hidden
    
    def __hash__(self):
        return hash(self.title)
    
    def __eq__(self, other):
        if isinstance(other, CategoryPage):
            return self.title == other.title
        return False
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def isInCategory(self, page):
        for pageCategory in page.categories():
            if pageCategory.title(underscore=True) == self.mwtitle:
                return True
        return False
    
    @property
    def mwtitle(self):
        return "Category:" + self.title
    
    @property
    def mwcontents(self):
        parentText = ""
        if self.parent:
            parentText = "[[" + self.parent.mwtitle + "]]"
            
        hiddenCat = ""
        if self.hidden:
            hiddenCat = "__HIDDENCAT__"
            
        return parentText + "\n" + hiddenCat
        
    def checkPage(self, page):
        return True
        
class DoxygenHTMLPage(DoxyMWPage):
    #Config values to change how the pages are made
    globalPrefix = None
    if "mediaWiki_docsPrefix" in doxymwglobal.config and doxymwglobal.config["mediaWiki_docsPrefix"] != "":
        globalPrefix = doxymwglobal.config["mediaWiki_docsPrefix"]
    else:
        raise DoxyMWConfigException("A docs prefix must be defined or we may clash with other names")
        
    globalCategory = None
    if "mediaWiki_docsCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_docsCategory"] != "":
        globalCategory = CategoryPage(doxymwglobal.config["mediaWiki_docsCategory"],hidden=True)
    else:
        raise DoxyMWConfigException("A docs category must be defined or we can't properly clean the docs up later")

        
    def __init__(self, fp, fn, type):
        #About the file this page came from (every file is a page)
        self.filepath = fp
        self.filename = fn
        
        #About the page itself
        self.type = type
        self.title = None
        self.displayTitle = None
        self.contents = None
        self.footer = None
        self.imgs = []
        
        #Extract all the data
        self.extract()
    
    #Extracts all the data from the file at self.filepath
    def extract(self):
        fp = open(self.filepath)
    
        #Extract the specific parts of the page for the wiki
        data = DoxygenHTMLExtractor(fp.read())
        
        if not data:
            raise DoxyMWException("Not enough content in doxygen document to create MediaWiki page in " + self.filename)
        
        #Check for invalid characters in title, may need to use a DisplayTitle to display class properly
        fakeTitle = re.sub("[\<\>\[\]\|\{\}_#]", "_", data["title"])
        if fakeTitle != data["title"] and doxymwglobal.config["mediaWiki_useFullDisplayTitle"]:
            #Invalid chars and are allowed to use unrestricted display title
            self.title = fakeTitle
            self.displayTitle = data["displayTitle"]
        else:
            #No invalid chars OR restricted display title
            #Just use the safe title
            self.title = fakeTitle
        
        self.contents = data["contents"]
        self.footer = data["footer"]
    
    #Converts all the data in this page to proper MediaWiki markup
    def convert(self, wikiPages):
        #Convert gathered data into MediaWiki markup (including links using wikiPages)
        self.contents, moreImgs = DoxygenHTMLConverter(self.contents, wikiPages)
        self.imgs += moreImgs
        self.footer, moreImgs = DoxygenHTMLConverter(self.footer, wikiPages)
        self.imgs += moreImgs
    
    #Gets the transclusion page this DoxygenHTML page should be referenced by
    def getTransclusionPage(self):
        return TransclusionPage(self.title, self)
    
    #Gets the page title
    @property
    def mwtitle(self):
        return DoxygenHTMLPage.globalPrefix + "_" + self.title
    
    #Gets the page contents
    @property
    def mwcontents(self):
        #The full contents is made up from multiple parts:
        #The noinclude DO NOT EDIT + link to transclusions (if they're enabled)
        #DisplayTitle (If there is one)
        #The actual contents of the page
        #The category
        
        #Sorting doesn't work too well with the original names
        #We reverse the order of the parts of the name from class to highest namespace
        sortKey = ".".join(reversed(self.title.split(".")))
        
        return ("<noinclude>" +
        "\nAUTOGENERATED CONTENT, DO NOT EDIT<br><br>" +
        "\nAny edits made to this page will be lost upon the next running of DoxyMWBot." +
        "\nTo add content alongside this documentation, " +
        
        ("edit [{{fullurl:" + self.title + "|redirect=no}} " + self.title + "] instead." if
        doxymwglobal.config["mediaWiki_setupTransclusions"]
        else "you must have transclusions enabled!") +
        
        "<br><br></noinclude>" +
        
        ("\n{{DISPLAYTITLE:" + self.displayTitle + "}}" if
        self.displayTitle
        else "") +
        
        "\n" + self.contents + 
        "\n" + self.footer +
        
        "\n<noinclude>" +
        "\n[[" + DoxygenHTMLPage.globalCategory.mwtitle + "]]" + 
        "\n[[" + DoxygenHTMLPage.globalCategory.mwtitle + "_" + self.type + "|" + sortKey + "]]" +
        "\n</noinclude>"
        )
    
    def checkPage(self, page):
        if not page.exists():
            return True
            
        #Must have our docs category to modify!
        return DoxygenHTMLPage.globalCategory.isInCategory(page)
        

class TransclusionPage(DoxyMWPage):
    #Config values to change how the pages are made
    globalPrefix = None
    if "mediaWiki_transclusionPrefix" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionPrefix"] != "":
        globalPrefix = doxymwglobal.config["mediaWiki_transclusionPrefix"]
        
    globalCategory = None
    if "mediaWiki_transclusionCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionCategory"] != "":
        globalCategory = CategoryPage(doxymwglobal.config["mediaWiki_transclusionCategory"],hidden=True)
    else:
        raise DoxyMWConfigException("A transclusion category must be defined or we can't properly clean them up later")
        
    globalExternCategory = None
    if "mediaWiki_transclusionExternalCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionExternalCategory"] != "":
        globalExternCategory = CategoryPage(doxymwglobal.config["mediaWiki_transclusionExternalCategory"])
        

    def __init__(self, title, target):
        self.title = title #Basic title of the transclusion page, same as doxygen docs page title
        self.target = target #Target DoxyMWPage of this transclusion page
       
    @property
    def mwtitle(self):
        return ((TransclusionPage.globalPrefix + "_" if TransclusionPage.globalPrefix else "")
            + self.title)
    
    @property
    def mwcontents(self):
        infoText = (
            "\n<!--"
            "\nTo add content alongside your coding documentation, you must edit this page."
            "\nRemove the redirect and add the text {{:" + self.mwtitle + "}} to transclude the coding documentation on this page"
            "\nIf you choose, you can rerun DoxyMWBot to append a transclusion to every non-redirect page you have created"
            "\n-->"
        )
        #Sorting doesn't work too well with the original names
        #We reverse the order of the parts of the name from class to highest namespace
        sortKey = ".".join(reversed(self.title.split(".")))
    
        return ("#REDIRECT [[" + self.target.mwtitle + "]]\n" + infoText + "\n\n" +
            "[[" + TransclusionPage.globalCategory.mwtitle + "]]" +
            ("[[" + TransclusionPage.globalExternCategory.mwtitle + "|" + sortKey + "]]" if TransclusionPage.globalExternCategory else "")
        )
        
    def checkPage(self, page):
        if not page.exists():
            return True
            
        #Must have our categories to modify!
        check = TransclusionPage.globalCategory.isInCategory(page)
        
        #Must also have external category if it's not a redirect page
        if TransclusionPage.globalExternCategory and not page.isRedirectPage():
            check = check and TransclusionPage.globalExternCategory.isInCategory(page)
        return check
    
    def updatePage(self, page):
        if not self.checkPage(page) and not doxymwglobal.option["debug"] == "unsafeUpdate":
            raise DoxyMWException("Page is not the correct page to be editted by this object")
        
        putText = ""
                    
        #If the page doesn't exist or is old redirect, make it as a blank redirect
        if not page.exists() or page.isRedirectPage():
            putText = self.mwcontents
            
        #If the page does exist, make it a transclusion page
        #This ONLY happens if the page is in our category (checkPage enforces this)
        else:
            page.get()
            transTest = "{{:" + self.target.mwtitle + "}}"
            if page.text.find(transTest) == -1:
                #Append the transclusion to the page, but only if it isn't already there
                putText = page.text + "\n" + transTest
        
        #If we changed the page, save it
        if putText != "":
            try:
                page.text = putText
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                raise DoxyMWException("Couldn't create page")
        
class BotUserPage(DoxyMWPage):
    @property
    def mwtitle(self):
        #TODO: Make username of the bot configurable
        #TODO: Don't use if not a separate bot account on this wiki for this bot
        return "User:DoxygenBot"
    
    @property
    def mwcontents(self):
        #TODO: Add usage here or something
        infoText = (
            "Hello, I am DoxyMWBot. I do things"
        )