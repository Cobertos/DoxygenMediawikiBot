import re
import hashlib
import os

import pywikibot
from bs4 import BeautifulSoup

import doxymwglobal

class DoxyMWException(Exception):
    pass

#Exception when the configuration isn't safe to use
class DoxyMWConfigException(DoxyMWException):
    pass

#An abstract base classes for all other page types
class DoxyMWPage(object):
    @property #Should return the MediaWiki title
    def mwtitle(self):
        raise NotImplementedError("Abstract class property should be implemented")
        
    @property #Should return the MediaWiki page contents
    def mwcontents(self):
        raise NotImplementedError("Abstract class property should be implemented")
    
    #Should check a DoxyMWPage to make sure it's the page we think (safety measure)
    def checkPage(self, site, page):
        raise NotImplementedError("Abstract class function should be implemented")
    
    #Should update/create a page to conform to the information stored in the object
    def updatePage(self, site, page):
        #Most classes use this
        if not self.checkPage(site, page) and not doxymwglobal.option["debug"] == "unsafeUpdate":
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
        
    def checkPage(self, site, page):
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
        #Check validity of file
        if not os.path.isfile(fp + "/" + fn):
            raise DoxyMWException("File " + fp + "/" + fn + " does not exist")
    
        #About the file this page came from (every file is a page)
        self.filepath = fp
        self.filename = fn
        
        #About the page itself
        self.type = type
        self.title = None
        self.displayTitle = None
        self.contents = None
        self.footer = None
        self.infobox = None
        self.imgs = []
        
        #Extract all the data
        self.extract()
    
    #Extracts all the data from the file at self.filepath
    def extract(self):
        fp = open(self.filepath + "/" + self.filename)
    
        #Extract the specific parts of the page for the wiki
        data = self.extractInternal(fp.read())
        
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
        
        #Build the infobox
        #Nav breadcrumb sort of thing
        navStr = ""
        if len(data["nav"]) > 0:
            for i in range(0, len(data["nav"])):
                tag = data["nav"][i]
                navStr += "<div>" + tag + "</div>"
                if i < len(data["nav"])-1: #Only add The dividers if it's not the last one
                    navStr += "<div>V</div>"
        
        #Summary links
        summaryStr = ""
        if len(data["summary"]) > 0:
            for i in range(0, len(data["summary"])):
                tag = data["summary"][i]
                summaryStr += "<div>" + tag + "</div>"
    
        self.infobox = (
        "<!--DoxyMWBot Infobox (modelled after Wikipedia's)-->" +
        "<div class=\"doxymw_infobox\">" +
        "<div class=\"head\">DoxyMWBot</div>" + 
        "<div>Type: <span class=\"doxymw_type doxymw_type" + self.type + "\">[[" + "TheCorrectCategory" + "|" + self.type + "]]</span></div>" + #TODO: Replace this with the category
        (("<div>Nav: " +
            "<div class=\"doxymw_nav\">" +
                navStr +
            "</div>" +
        "</div>") if navStr != "" else "") +
        summaryStr +
        "<div>Full Class Hierarchy</div>" +
        #"<div>[[User:Whoever DoxyMWBot]]</div>" + #TODO: Readd when we get theuser page fully working
        "<div>[http://doxygen.org Doxygen]</div>" +
        "</div>" +
        "<!--End DoxyMWBot Infobox-->")
        
    #Converts all the data in this page to proper MediaWiki markup
    def convert(self, wikiPages):
        #Convert gathered data into MediaWiki markup (including links using wikiPages)
        self.contents, moreImgs = self.convertInternal(self.contents, wikiPages)
        self.imgs += moreImgs
        self.footer, moreImgs = self.convertInternal(self.footer, wikiPages)
        self.imgs += moreImgs
        self.infobox, moreImgs = self.convertInternal(self.infobox, wikiPages)
        self.imgs += moreImgs
    
    #Gets the transclusion page this DoxygenHTML page should be referenced by
    def getTransclusionPage(self):
        return TransclusionPage(self.title, self)
    
    #Function that returns data extracted from Doxygen file for MediaWiki page
    #Returns a dictionary with
    # + title: The title of the Doxygen file, straight unicode
    # + nav: List of <a> tags from the upper breadcrumb like navigation thing
    # + summary: Links in the summary div (like "List of members, Public members, Protected members" etc...)
    # + displayTitle: Title of the Doxygen file, with HTML entities
    # + contents: The body of the Doxygen file
    def extractInternal(self, text):
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
        
        #Find the nav
        data["nav"] = []
        select = onlyOne(soup.select("#nav-path > ul"), "nav")
        if not select:
            pass #May not be present, so we just leave this an an empty array
        else:
            for tag in select.select("li > a.el"):
                data["nav"].append(tag.decode(formatter="html"))
        
        #Find the summary links
        data["summary"] = []
        select = onlyOne(soup.select("div.header div.summary"), "summary")
        if not select:
            pass #May not be present, so we just leave this an an empty array
        else:
            for tag in select.select("a"):
                data["summary"].append(tag.decode(formatter="html"))
        
        #Find the contents
        select = onlyOne(soup.select("div.contents"), "contents")
        if not select:
            return None
        data["contents"] = select.decode_contents(formatter="html")
        
        #Footer for attribution and compile time info
        select = onlyOne(soup.select("address.footer"), "footer")
        if not select:
            return None
        data["footer"] = select.decode_contents(formatter="html")
        
        return data
        
    #Function that translates all HTML to MediaWiki markup with the least amount of work
    #Returns two objects in a tuple
    # + text contains the translated HTML for the wiki
    # + imgs contains all identified images that should be uploaded
    def convertInternal(self, text, wikiPages):
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
                if link == "" and fragment == "": #Empty link
                    newStr = ""
                elif link == "": #Local link with only fragment
                    internalLink = True
                else: #Test if it matches an internal file, if not, external link
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
            imgs.append(ImagePage(self.filepath, img.attrs["src"]))
            
            #Convert the image
            newStr = "[[File:" + img.attrs["src"] + "]]"
            img.replace_with(newStr)
            
        #Convert <maps>
        #For now just delete them, we'll have to rely on a MW extension for this one later
        for map in soup("map"):
            map.replace_with("") 
            
        return (soup.decode_contents(formatter="html"), imgs)
    
    #Gets the page title
    @property
    def mwtitle(self):
        return DoxygenHTMLPage.globalPrefix + "_" + self.title
    
    #Gets the page contents
    @property
    def mwcontents(self):
        #Sorting doesn't work too well with the original names
        #We reverse the order of the parts of the name from class to highest namespace
        sortKey = ".".join(reversed(self.title.split(".")))
        
        #The noinclude DO NOT EDIT + link to transclusions (if they're enabled)
        return ("<noinclude>" +
        "\n'''''Do not edit this autogenerated page.'''''" +
        "\n''Edits will be lost upon running DoxyMWBot again. " +
        ("Edit [{{fullurl:" + self.title + "|redirect=no}} " + self.title + "] instead." if
        doxymwglobal.config["mediaWiki_setupTransclusions"]
        else "You must turn on transclusion to generate pages for you to add your content.") + "''" +
        "</noinclude>" +
        
        #DisplayTitle (If there is one)
        ("\n{{DISPLAYTITLE:" + self.displayTitle + "}}" if
        self.displayTitle
        else "") +
        
        #The doxygen infobox and actual page contents
        "\n" + self.infobox +
        "\n" + self.contents + 
        "\n" + self.footer +
        
        #The categories
        "\n<noinclude>" +
        "\n[[" + DoxygenHTMLPage.globalCategory.mwtitle + "]]" + 
        "\n[[" + DoxygenHTMLPage.globalCategory.mwtitle + "_" + self.type + "|" + sortKey + "]]" +
        "\n</noinclude>"
        )
    
    def checkPage(self, site, page):
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
        
    def checkPage(self, site, page):
        if not page.exists():
            return True
            
        #Must have our categories to modify!
        check = TransclusionPage.globalCategory.isInCategory(page)
        
        #Must also have external category if it's not a redirect page
        if TransclusionPage.globalExternCategory and not page.isRedirectPage():
            check = check and TransclusionPage.globalExternCategory.isInCategory(page)
        return check
    
    def updatePage(self, site, page):
        if not self.checkPage(site, page) and not doxymwglobal.option["debug"] == "unsafeUpdate":
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

class ImagePage(DoxyMWPage):
    globalCategory = CategoryPage(DoxygenHTMLPage.globalCategory.title + "_IMAGE", parent=DoxygenHTMLPage.globalCategory)

    def __init__(self, fp, fn):
        #Check validity of file
        if not os.path.isfile(fp + "/" + fn):
            raise DoxyMWException("File " + fp + "/" + fn + " does not exist")
    
        self.filepath = fp
        self.filename = fn
    
    @property
    def mwtitle(self):
        return "File:" + self.filename
    
    @property
    def mwcontents(self):
        return "Autogenerated Doxygen Image\n" + "[[" + ImagePage.globalCategory.mwtitle + "]]"
    
    def checkPage(self, site, page):
        return True
    
    def updatePage(self, site, page):
        imgPage = pywikibot.FilePage(site, self.filename)
        
        #If page exists, test hash against uploaded image
        try:
            #Throws exception on no page existing (NoPage)
            currSha1 = imgPage.latest_file_info.sha1
            
            #Check the sha1 so we don't update needlessly
            fp = open(self.filepath + "/" + self.filename, "rb")
            sha1 = hashlib.sha1()
            sha1.update(fp.read())
            if currSha1 == sha1.hexdigest():
                doxymwglobal.msg(doxymwglobal.msgType.info, "Image skipped because hashes were equal")
                return
        except pywikibot.exceptions.NoPage:
            pass
        
        #Otherwise upload that bad boy/girl/non-binary gender entity
        doxymwglobal.msg(doxymwglobal.msgType.info, "Image " + self.filename + " being uploaded")
        site.upload(imgPage, source_filename=self.filepath + "/" + self.filename, comment=self.mwcontents, ignore_warnings=True)
                
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