import re
import hashlib
import os

import pywikibot
from pywikibot import pagegenerators
from pywikibot.pagegenerators import GeneratorFactory
from bs4 import BeautifulSoup

import doxymwglobal

#Small class for generating title and displayTitle
#This doesnt include namespace, fragment, or anything else, just titles
# + title - Normalized title
# + displayTitle - The least normalized title. Depends on your use of avoid
class DoxyMWTitle(object):

    def __init__(self, title, avoid=True):
        #Soft normalize first to avoid possible mismatch between normalized and non-normalized
        if avoid:
            title = DoxyMWTitle.softNorm(title)
    
        self.reasonFail = "No failure occured"
        
        self.title = DoxyMWTitle.normalize(title)
        self._displayTitle = None
        #Non-normalized title != normalized, we need a display title (if supported by config)
        if title != self.title and doxymwglobal.config["mediaWiki_useFullDisplayTitle"]:
            self._displayTitle = title
            
        if self.title == None:
            raise DoxyMWException("Title failed normalization. " + self.reasonFail)
    
    @property
    def displayTitle(self):
        if self._displayTitle:
            return self._displayTitle
        else:
            return self.title
    
    @property
    def mwdisplaytitle(self):
        return ("{{DISPLAYTITLE:" + self._displayTitle + "}}" if self._displayTitle else "")
    
    #A softer less destructive normalization based on some MediaWiki title rules
    @staticmethod
    def softNorm(title):
        normtitle = re.sub("_", " ", title) #_ are ' 's in MediaWiki titles
        normtitle = re.sub(" +", " ", normtitle) #' 's are collapsed to one space
        normtitle = normtitle.strip() #Leading and trailing spaces are stripped
        normtitle = normtitle[:1].capitalize() + normtitle[1:] #And the first letter is capitalized
        return normtitle
    
    #Normalize a title and test to see if it passes the Link test. If we fail, return None
    #We may fail because this doesn't normalize ALL titles but most. New checks may be added to pywikibot later too
    #All invalid characters replaced with ! (And then we rely on the fact that there's display titles)
    @staticmethod
    def hardNorm(title):
        #Replace illegal sequences with !
        normtitle = re.sub(pywikibot.Link.illegal_titles_pattern, "!", title)
        #Truncate to 255 bytes
        if len(normtitle) > 255:
            normtitle = normtitle[:255]
    
        #Test it with pywikibot.Link
        try:
            link = pywikibot.Link(normtitle)
            link.parse() #Will cause it to fail if not a valid title
        except pywikibot.InvalidTitle as e: #Something else was wrong
            self.reasonFail = str(e)
            return None
        
        return normtitle
    
    #Chain the two together
    @staticmethod
    def normalize(title):
        return DoxyMWTitle.hardNorm(DoxyMWTitle.softNorm(title))
        
#Strategies for updating pages - Used by pages classes to determine how to "put" their contents
class DoxyMWStrategy(object):
    def __init__(self, canCreate=True, canEdit=True, checkPageEdit=None):
        self.canCreate = canCreate
        self.canEdit = canEdit
        
        if checkPageEdit and not callable(checkPageEdit):
            raise TypeError("checkPageEdit must be a function")
            
        self.checkPageEdit = checkPageEdit

    #The default check page that determines whether or not we can modify the page (safety measure)
    def checkPage(self, page):
        if "unsafeUpdate" in doxymwglobal.option["debug"]:
            return True
        
        if self.canCreate and not page.exists():
            return True
        
        #checkPageEdit should check to make sure the page is the one we want to edit (e.g. it's not already a user made page or something) (safety measure)
        if self.canEdit and (not self.checkPageEdit or self.checkPageEdit(page)):
            return True
    
        return False
    
    def updatePage(self, pageData, page):
        raise NotImplementedError("Abstract method should be implemented")
        
    def deletePage(self, pageData, page):
        raise NotImplementedError("Abstract method should be implemented")

#We own the entire page, just update it directly    
class FullPageStrategy(DoxyMWStrategy):
    def updatePage(self, pageData, page):
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.debug, "Page " + page.title() + " failed strategy edit check for pageData " + pageData.mwtitle)
            return False
            
        try:
            if page.exists() and not page.isRedirectPage():
                page.get()
                if page.text == pageData.mwcontents:
                    return False #Don't need to make or update
                    
            page.text = pageData.mwcontents
            page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Page " + page.title() + " could not be updated: " + str(e))
            return False
        
        return True
    
    def deletePage(self, page):
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.debug, "Page " + page.title() + " failed strategy edit check.")
            return False
            
        try:
            page.delete(reason="", prompt=doxymwglobal.option["interactive"])
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Page " + page.title() + " could not be deleted: " + str(e))
            return False
            
        #TODO: There is no better way to tell if the user actually deleted the page through the prompt (unless we supplied our own)
        #That is... without performing another API query
        return True
            
#Only updates the stuff between some delimiter on the page with mwcontents
class SectionStrategy(DoxyMWStrategy):
    def __init__(self, startDelim=None, endDelim=None, **kwargs):
        super().__init__(**kwargs)
        if not startDelim or not endDelim:
            raise TypeError("One or both delimiters were not supplied.")
        
        self.startDelim = startDelim
        self.endDelim = endDelim

    def updatePage(self, pageData, page):
        return self._updatePage(pageData.mwcontents, page)
    
    
    def _updatePage(self, contents, page):
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.debug, "Page " + page.title() + " failed strategy edit check.")
            return False
        
        try:
            putText = ""
            if not page.exists():
                putText = self.startDelim + "\n" + contents + "\n" + self.endDelim
            else:
                #Page exists, look for the delimiters
                text = page.get()
                startPos = text.find(self.startDelim)
                endPos = text.rfind(self.endDelim)
                #Found both of them!
                if startPos != -1 and endPos != -1: 
                    #startPos = startPos
                    endPos = endPos + len(self.endDelim)
                    putText = text[:startPos] + self.startDelim + "\n" + contents + "\n" + self.endDelim + text[endPos:]
                #Only one?!
                elif startPos != -1 or endPos != -1: 
                    doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not edit page, one delimiter found but not the other!")
                    return
                #Neither, just append a new section to the page    
                else:
                    putText = text + "\n" + self.startDelim + "\n" + contents + "\n" + self.endDelim
            
            page.text = putText
            page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Page " + page.title() + " could not be updated: " + str(e))
            return False
        
        return True
        
    def deletePage(self, page):
        return self._updatePage("", page)
        
#For updating files (images)
class FileStrategy(FullPageStrategy):
    #Same delete but different updatePage
    def updatePage(self, pageData, page):
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.debug, "Page " + page.title() + " failed strategy edit check for pageData " + pageData.mwtitle)
            return False
        
        site = pywikibot.Site() #TODO: Bad, replace this
        filePage = pywikibot.FilePage(site, pageData.normtitle.title)
        
        #If page exists, test hash against uploaded image
        try:
            #Throws exception on no page existing (NoPage)
            currSha1 = filePage.latest_file_info.sha1
            
            #Check the sha1 so we don't update needlessly
            if currSha1 == pageData.sha1:
                doxymwglobal.msg(doxymwglobal.msgType.debug, "File " + pageData.mwtitle + " skipped because hashes were equal")
                return False
        except pywikibot.exceptions.NoPage:
            pass
        
        #Otherwise upload that bad boy/girl/non-binary gender entity
        doxymwglobal.msg(doxymwglobal.msgType.info, "File " + pageData.mwtitle + " being uploaded")
        site.upload(filePage, source_filename=pageData.filepath + "/" + pageData.filename, comment=pageData.mwcontents, ignore_warnings=True)
        return True

#An base class for all other page types
#This class shouldn't be used directly though
class DoxyMWPage(object):
    #Basic functionality of this class
    #Sets up basic permissions on what we can do for the page, enforced in checkPage
    def __init__(self, normtitle=None, updateStrategy=None):
        self.sortKey = None
        self.categories = []
        if not updateStrategy or not isinstance(updateStrategy, DoxyMWStrategy):
            raise TypeError("updateStrategy must be a DoxyMWStrategy")
        self.strategy = updateStrategy
        
        #TODO: Better way to guarentee normtitle is not none
        #I don't want to force it to have to be passed. Maybe have a separate mwdisplaytitle that returns the displayed title?
        self.normtitle = normtitle

    def __hash__(self):
        return hash(self.mwtitle)
    
    def __eq__(self, other):
        if isinstance(other, DoxyMWPage):
            return self.mwtitle == other.mwtitle
        return False
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def hasCategory(self, cat):
        return cat in self.categories
    
    def addCategory(self, cat):
        self.categories.append(cat)

    #Stuff that should be overriden based on your uses
    @property #Should return a list of pages to make
    def newPages(self):
        pages = [self]
        pages.extend(self.categories)
        return pages
        
    @property #Should return the MediaWiki title
    def mwtitle(self):
        raise NotImplementedError("Abstract class property should be implemented")
        
    @property #Should return the MediaWiki page contents
    def mwcontents(self):
        #Display title
        str = "\n" + self.normtitle.mwdisplaytitle
        #All categories (self.sortKey is shared between all categories unforntunately, no better way to do this atm)
        sortKeyStr = ""
        if self.sortKey:
            sortKeyStr = "|" + self.sortKey
        for cat in self.categories:
            str += "\n[[" + cat.mwtitle + sortKeyStr + "]]"
            
        return str
    
    #Should get the page from the mediawiki given the site
    def getPage(self, site):
        gen = pagegenerators.PagesFromTitlesGenerator([self.mwtitle])
        try:
            page = gen.__next__()
            return page
        except StopIteration as e:
            raise doxymwglobal.DoxyMWException("No page generated in generator")
    
    #Returns the strategy this page should use
    @staticmethod
    def getStrategy(**kwargs):
        raise NotImplementedError("Abstract class property should be implemented")
    
    #Updates a page (dispatched to given updateStrategy)
    def updatePage(self, site):
        page = self.getPage(site)
        return self.strategy.updatePage(self, page)
    
    #Deletes a page (dispatched to given updateStrategy)    
    def deletePage(self, site):
        page = self.getPage(site)
        return self.strategy.deletePage(page)
        
class CategoryPage(DoxyMWPage):
    def __init__(self, title, parent=None, hidden=False, **kwargs):
        super().__init__(normtitle=DoxyMWTitle(title), updateStrategy=CategoryPage.getStrategy(**kwargs))
        if parent:
            self.addCategory(parent)
        self.hidden = hidden
    
    @staticmethod
    def getStrategy(**kwargs):
        return FullPageStrategy(**kwargs)
    
    @property
    def mwtitle(self):
        return "Category:" + self.normtitle.title
    
    @property
    def mwcontents(self):
        hiddenCat = ""
        if self.hidden:
            hiddenCat = "__HIDDENCAT__"
            
        return hiddenCat + super().mwcontents
    
    def isInCategory(self, page):
        for pageCategory in page.categories():
            if pageCategory.title() == self.mwtitle:
                return True
        return False
        
class DoxygenHTMLPage(DoxyMWPage):
    #Config values to change how the pages are made
    globalPrefix = None
    if "mediaWiki_docsPrefix" in doxymwglobal.config and doxymwglobal.config["mediaWiki_docsPrefix"] != "":
        globalPrefix = doxymwglobal.config["mediaWiki_docsPrefix"]
    else:
        raise doxymwglobal.ConfigException("A docs prefix must be defined or we may clash with other names")
        
    globalCategory = None
    if "mediaWiki_docsCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_docsCategory"] != "":
        globalCategory = CategoryPage(doxymwglobal.config["mediaWiki_docsCategory"],hidden=True)
    else:
        raise doxymwglobal.ConfigException("A docs category must be defined or we can't properly clean the docs up later")
        
    globalNavCategory = None
    if "mediaWiki_navCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_navCategory"] != "":
        globalNavCategory = CategoryPage(doxymwglobal.config["mediaWiki_navCategory"])
    else:
        raise doxymwglobal.ConfigException("A nav category must be defined")
    
    @staticmethod
    def getStrategy(**kwargs):
        def checkPageEdit(page):
            #Must have our docs category to modify!
            return DoxygenHTMLPage.globalCategory.isInCategory(page)
        return FullPageStrategy(checkPageEdit=checkPageEdit, **kwargs)
    
    def __init__(self, fp, fn, type, **kwargs):
        #TODO:We set normtitle late in this class, fix this
        super().__init__(normtitle=None, updateStrategy=DoxygenHTMLPage.getStrategy(**kwargs))
        
        #Check validity of file
        if not os.path.isfile(fp + "/" + fn):
            raise doxymwglobal.DoxyMWException("File " + fp + "/" + fn + " does not exist")
    
        #About the file this page came from (every file is a page)
        self.filepath = fp
        self.filename = fn
        
        #About the page itself
        self.type = type
        self.normtitle = None
        self.data = None
        self.infoBoxPages = []
        self.imgs = []
        
        #Add categories
        self.addCategory(DoxygenHTMLPage.globalCategory)
        
        #Extract all the data
        self.extract()
    
    #Extracts all the data from the file at self.filepath
    def extract(self):
        fp = open(self.filepath + "/" + self.filename)
    
        #Extract the specific parts of the page for the wiki
        self.data = self.extractInternal(fp.read())
        if not self.data:
            raise doxymwglobal.DoxyMWException("Not enough content in doxygen document to create MediaWiki page in " + self.filename)
            
        #Set title
        self.normtitle = DoxyMWTitle(self.data["title"], avoid=False)
        
        #Sorting doesn't work too well with the original names
        #We reverse the order of the parts of the name from class to highest namespace
        self.sortKey = ".".join(reversed(self.normtitle.title.split(".")))
    
    #Converts all the data in this page to proper MediaWiki markup
    def convert(self, wikiPages):
        for key, value in self.data.items():
            if key == "title":
                continue
            
            if isinstance(value, list):
                values = []
                for v in value:
                    newValue, newImgs = self.convertInternal(v, wikiPages)
                    values.append(newValue)
                    self.imgs += newImgs
                    
                self.data[key] = values
            else:
                self.data[key], newImgs = self.convertInternal(value, wikiPages)
                self.imgs += newImgs
    
    #Add a page to the list for that will go into the info box
    def addInfoBoxPage(self, page):
        self.infoBoxPages.append(page)
    
    #Gets the transclusion page this DoxygenHTML page should be referenced by
    def getTransclusionPage(self):
        return TransclusionPage(self.normtitle, self)
    
    #Function that returns data extracted from Doxygen file for MediaWiki page
    #Returns a dictionary with
    # + title: The title of the Doxygen file, straight unicode
    # + nav: List of <a> tags from the upper breadcrumb like navigation thing
    # + summary: Links in the summary div (like "List of members, Public members, Protected members" etc...)
    # + contents: The body of the Doxygen file
    # + footer: The html of the bottom of the page with the build time and doxygen logo
    def extractInternal(self, text):
        soup = BeautifulSoup(text)
        data = {}
        
        def onlyOne(tagList, which):
            if len(tagList) <= 0:
                doxymwglobal.msg(doxymwglobal.msgType.debug, "No " + which + " found")
                return None
            elif len(tagList) > 1:
                doxymwglobal.msg(doxymwglobal.msgType.debug, "Ambiguous " + which)
            return tagList[0]
        
        #Find the title
        select = onlyOne(soup.select("div.header div.title"), "title")
        if not select:
            return None
        data["title"] = select.decode_contents(formatter=None) #Straight unicode
        
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
                if link == "" and (fragment == "" or fragment == "#"): #Empty link
                    newStr = ""
                elif link == "": #Local link with only fragment
                    internalLink = True
                else: #Test if it matches an internal file, if not, external link
                    for page in wikiPages:
                        if link == page.filename:
                            internalLink = True
                            link = page.normtitle.title
                            break
                
                #What's the content?
                text = a.string
                tags = a.select("*")
                if text: #Simple text string
                    if not internalLink:
                        newStr = "[" + href + " " + text + "]"
                    else:
                        newStr = "[[" + link + fragment + "|" + text + "]]"
                elif len(tags) == 1 and tags[0].name == "img": #One image inside the a tag
                    img = tags[0]
                    imgs.append(ImagePage(self.filepath, img.attrs["src"]))
                    newStr = "[[File:" + img.attrs["src"] + "|link=" + link + fragment + "]]"
                else: #Something else
                    doxymwglobal.msg(doxymwglobal.msgType.debug, "Unhandled link with unknown contents")
                    newStr = ""
                    
                a.replace_with(newStr)
            
            #A named anchor
            elif "name" in a.attrs:
                newStr = soup.new_tag("span")
                newStr.attrs["id"] = a.attrs["name"] #Named anchors in MediaWiki just use the id
                newStr.attrs["style"] = "width:0;height:0;font-size:0;"
            
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
    
    @property
    def newPages(self):
        pages = super().newPages
        
        for imgPageData in self.imgs:
            pages.extend(imgPageData.newPages) #Images
        return pages
    
    #Gets the page title
    @property
    def mwtitle(self):
        return DoxygenHTMLPage.globalPrefix + " " + self.normtitle.title
    
    #Gets the page contents
    @property
    def mwcontents(self):
        #Do not use <img>, <a>, or other non-MediaWiki accepted HTML tags in here!
        
        #Build the infobox
        #Nav breadcrumb sort of thing
        navStr = ""
        if len(self.data["nav"]) > 0:
            navStr = "<div>Nav: <div class=\"doxymw_nav\">"
            for i in range(0, len(self.data["nav"])):
                tag = self.data["nav"][i]
                navStr += "<div>" + tag + "</div>"
                if i < len(self.data["nav"])-1: #Only add The dividers if it's not the last one
                    navStr += "<div>V</div>"
            navStr += "</div></div>"
        
        #Summary links
        summaryStr = ""
        if len(self.data["summary"]) > 0:
            for tag in self.data["summary"]:
                summaryStr += "<div>" + tag + "</div>"
    
        extraStr = ""
        if len(self.infoBoxPages) > 0:
            for page in self.infoBoxPages:
                extraStr += "<div>[[" + page.mwtitle + "|" + page.normtitle.displayTitle + "]]</div>"
    
        navCategoryType = "Category:" + DoxygenHTMLPage.globalNavCategory.normtitle.title + " " + self.type
    
        infobox = (
        "<!--DoxyMWBot Infobox (modelled after Wikipedia's)-->" +
        "<div class=\"doxymw_infobox\">" +
        "<div class=\"head\">DoxyMWBot</div>" + 
        "<div>Type: <span class=\"doxymw_type doxymw_type" + self.type + "\">[[:" + navCategoryType + "]]</span></div>" +
        navStr +
        summaryStr +
        extraStr +
        "</div>" +
        "<!--End DoxyMWBot Infobox-->")
        
        return ("<noinclude>" +
        "\n'''''Do not edit this autogenerated page.'''''" +
        "\n''Edits will be lost upon running DoxyMWBot again. " +
        ("Edit [{{fullurl:" + self.normtitle.title + "|redirect=no}} " + self.normtitle.title + "] instead." if
        doxymwglobal.config["mediaWiki_setupTransclusions"]
        else "You must turn on transclusion to generate pages for you to add your content.") + "''" +
        "</noinclude>" +
        
        #The doxygen infobox and actual page contents
        "\n" + infobox +
        "\n" + self.data["contents"] + 
        "\n" + self.data["footer"] + "| <small>DoxyMWBot is in no way affiliated with Doxygen.</small>" +
        
        #Other stuff
        "\n<noinclude>" +
        super().mwcontents +
        "\n</noinclude>"
        )
        

class TransclusionPage(DoxyMWPage):
    #Config values to change how the pages are made
    globalPrefix = None
    if "mediaWiki_transclusionPrefix" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionPrefix"] != "":
        globalPrefix = doxymwglobal.config["mediaWiki_transclusionPrefix"]
        
    globalCategory = None
    if "mediaWiki_transclusionCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionCategory"] != "":
        globalCategory = CategoryPage(doxymwglobal.config["mediaWiki_transclusionCategory"],hidden=True)
    else:
        raise doxymwglobal.ConfigException("A transclusion category must be defined or we can't properly clean them up later")

    @staticmethod
    def getStrategy(**kwargs):
        def checkPageEdit(page):
            #Must have our category and should only edit redirects (never edit a user editted transclusion page)
            return TransclusionPage.globalCategory.isInCategory(page) and page.isRedirectPage()
        return FullPageStrategy(checkPageEdit=checkPageEdit, **kwargs)

    def __init__(self, normtitle, target, **kwargs):
        super().__init__(normtitle=normtitle, updateStrategy=TransclusionPage.getStrategy(**kwargs))
        self.normtitle = normtitle #Basic title of the transclusion page, same as doxygen docs page title
        self.target = target #Target DoxyMWPage of this transclusion page
        self.sortKey = self.target.sortKey
        
        self.addCategory(TransclusionPage.globalCategory)
    
    @property
    def mwtitle(self):
        return ((TransclusionPage.globalPrefix + " " if TransclusionPage.globalPrefix else "")
            + self.normtitle.title)
    
    @property
    def mwcontents(self):
        infoText = (
            "\n<!--"
            "\nTo add content alongside your coding documentation, you must edit this page."
            "\nRemove the redirect and add the text {{:" + self.target.mwtitle + "}} to transclude the coding documentation on this page"
            "\nIf you choose, you can rerun DoxyMWBot to append a transclusion to every non-redirect page you have created"
            "\n-->"
        )
    
        return "#REDIRECT [[" + self.target.mwtitle + "]]" + infoText + "\n" + super().mwcontents

class ImagePage(DoxyMWPage):
    globalCategory = CategoryPage(DoxygenHTMLPage.globalCategory.normtitle.title + " IMAGE", parent=DoxygenHTMLPage.globalCategory)

    @staticmethod
    def getStrategy(**kwargs):
        return FileStrategy(**kwargs)
    
    def __init__(self, fp, fn, **kwargs):
        super().__init__(normtitle=DoxyMWTitle(fn), updateStrategy=ImagePage.getStrategy(**kwargs), **kwargs)
        
        #Check validity of file
        if not os.path.isfile(fp + "/" + fn):
            raise doxymwglobal.DoxyMWException("File " + fp + "/" + fn + " does not exist")
    
        self.filepath = fp
        self.filename = fn
        self.addCategory(ImagePage.globalCategory)
        
        #Check the sha1 for checking against the currently uploaded image later
        fp = open(self.filepath + "/" + self.filename, "rb")
        sha1 = hashlib.sha1()
        sha1.update(fp.read())
        self.sha1 = sha1.hexdigest()
    
    @property
    def mwtitle(self):
        return "File:" + self.normtitle.title
    
    @property
    def mwcontents(self):
        return "Autogenerated Doxygen Image\n" + super().mwcontents
        
class BotUserPage(DoxyMWPage):

    @staticmethod
    def getStrategy(**kwargs):
        return FullPageStrategy(**kwargs)

    def __init__(self, site, **kwargs):
        super().__init__(normtitle=DoxyMWTitle(site.user()), updateStrategy=BotUserPage.getStrategy(**kwargs))
        self.addCategory(DoxygenHTMLPage.globalCategory)
        
        if not os.path.isfile("./README.md"):
            raise doxymwglobal.DoxyMWException("File " + file + " does not exist")
        
    @property
    def mwtitle(self):
        return "User:" + self.normtitle.title
    
    @property
    def mwcontents(self):
        fp = open("./README.md", "rt")
        readme = "\n" + fp.read() + "\n"
    
        return (
            "<nowiki>Hello, I am DoxyMWBot >:]" +
            "\n" + "This project is in no way affiliated with Doxygen" +
            "\n" + "More stuff will go here eventually, a FAQ, better description, etc" +
            readme + "</nowiki>" + super().mwcontents
        )
        
class StylesPage(DoxyMWPage):

    @staticmethod
    def getStrategy(**kwargs):
        return SectionStrategy(startDelim="/*START DOXYMWBOT*/", endDelim="/*END DOXYMWBOT*/", **kwargs)

    def __init__(self, **kwargs):
        super().__init__(normtitle=DoxyMWTitle("MediaWiki:Common.css"), updateStrategy=StylesPage.getStrategy(**kwargs))
        self.files = ["./modifiedDoxygenStyles.css", "./doxymwbotStyles.css"]
        
        for file in self.files:
            if not os.path.isfile(file):
                raise doxymwglobal.DoxyMWException("File " + file + " does not exist")
        
    @property
    def mwtitle(self):
        return "MediaWiki:Common.css"
    
    @property
    def mwcontents(self):
        putText = ""
        
        #Read each of our stylesheets
        for file in self.files:
            fp = open(file, "rt")
            putText += "\n" + fp.read() + "\n"
            
        return putText
        