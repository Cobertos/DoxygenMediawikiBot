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
# + displayTitle - blank string or a display title fragment
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
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Title failed normalization. " + self.reasonFail)
    
    @property
    def displayTitle(self):
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

#An base class for all other page types
class DoxyMWPage(object):

    #Sets up basic permissions on what we can do for the page, enforced in checkPage
    def __init__(self, canCreate=True, canEdit=True):
        self.canCreate = canCreate
        self.canEdit = canEdit

    @property #Should return a list of pages to make
    def newPages(self)
        return [self]
        
    @property #Should return the MediaWiki title
    def mwtitle(self):
        raise NotImplementedError("Abstract class property should be implemented")
        
    @property #Should return the MediaWiki page contents
    def mwcontents(self):
        raise NotImplementedError("Abstract class property should be implemented")
    
    #Should get the page from the mediawiki given the site
    def getPage(self, site):
        gen = pagegenerators.PagesFromTitlesGenerator([self.mwtitle])
        try:
            page = gen.__next__()
            return page
        except StopIteration as e:
            raise doxymwglobal.DoxyMWException("No page could be found")
    
    #The default check page that determines whether or not we can modify the page (safety measure)
    def checkPage(self, page):
        if "unsafeUpdate" in doxymwglobal.option["debug"]:
            return True
        
        if self.canCreate and not page.exists():
            return True
        
        if self.canEdit and self.checkPageEdit(page):
            return True
    
        return False
    
    #Should check a DoxyMWPage to make sure it's the page we want to edit (like the user didnt already make a page there or something) (safety measure)
    def checkPageEdit(self, page):
        raise NotImplementedError("Abstract class function should be implemented")
    
    #Should update/create a page to conform to the information stored in the object
    def updatePage(self, site):
        raise NotImplementedError("Abstract class function should be implemented")

#Updates the entire page with content in mwcontents        
class DoxyMWUpdatePage(DoxyMWPage):
    def updatePage(self, site):
        page = self.getPage(site)
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Page failed safety check, will not be editted")
            return False
        
        try:
            if page.exists():
                page.get()
                if page.text == self.mwcontents:
                    return False #Don't need to make or update
                    
            page.text = self.mwcontents
            page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            raise doxymwglobal.DoxyMWException("Couldn't create page")
        
        return True
            
#Only updates the stuff between some delimiter on the page with mwcontents
class DoxyMWReplaceSectionPage(DoxyMWPage):
    def updatePage(self, site):
        page = self.getPage(site)
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Page failed safety check, will not be editted")
            return False
        
        startDelimiter = "/*START DOXYMWBOT*/"
        endDelimiter = "/*END DOXYMWBOT*/"
        try:
            putText = ""
            if not page.exists():
                putText = startDelimiter + "\n" + self.mwcontents + "\n" + endDelimiter
            else:
                #Page exists, look for the delimiters
                text = page.get()
                startPos = text.find(startDelimiter)
                endPos = text.rfind(endDelimiter)
                #Found both of them!
                if startPos != -1 and endPos != -1: 
                    #startPos = startPos
                    endPos = endPos + len(endDelimiter)
                    putText = text[:startPos] + startDelimiter + "\n" + self.mwcontents + "\n" + endDelimiter + text[endPos:]
                #Only one?!
                elif startPos != -1 or endPos != -1: 
                    doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not edit page, one delimiter found but not the other!")
                    return
                #Neither, just append a new section to the page    
                else:
                    putText = text + "\n" + startDelimiter + "\n" + self.mwcontents + "\n" + endDelimiter
                    
            if putText == "":
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not edit page, some unknown delimiter failure")
                return False
            
            page.text = putText
            page.save()
        except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
            raise doxymwglobal.DoxyMWException("Couldn't create page")
        
        return True
        
class CategoryPage(DoxyMWUpdatePage):
    def __init__(self, title, parent=None, hidden=False, **kwargs):
        super().__init__(**kwargs)
        self.normtitle = DoxyMWTitle(title)
        self.parent = parent
        self.hidden = hidden
    
    def __hash__(self):
        return hash(self.normtitle.title)
    
    def __eq__(self, other):
        if isinstance(other, CategoryPage):
            return self.normtitle.title == other.normtitle.title
        return False
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
    def isInCategory(self, page):
        for pageCategory in page.categories():
            if pageCategory.title() == self.mwtitle:
                return True
        return False
    
    @property
    def mwtitle(self):
        return "Category:" + self.normtitle.title
    
    @property
    def mwcontents(self):
        parentText = ""
        if self.parent:
            parentText = "[[" + self.parent.mwtitle + "]]"
        
        hiddenCat = ""
        if self.hidden:
            hiddenCat = "__HIDDENCAT__"
            
        return parentText + "\n" + self.normtitle.displayTitle + "\n" + hiddenCat
        
    def checkPageEdit(self, page):
        return True
        
class DoxygenHTMLPage(DoxyMWUpdatePage):
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
        globaNavCategory = CategoryPage(doxymwglobal.config["mediaWiki_navCategory"],hidden=True)
    else:
        raise doxymwglobal.ConfigException("A nav category must be defined")
    
    def __init__(self, fp, fn, type, **kwargs):
        super().__init__(**kwargs)
        
        #Check validity of file
        if not os.path.isfile(fp + "/" + fn):
            raise doxymwglobal.DoxyMWException("File " + fp + "/" + fn + " does not exist")
    
        #About the file this page came from (every file is a page)
        self.filepath = fp
        self.filename = fn
        
        #About the page itself
        self.type = type
        self.title = None
        self.normtitle = None
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
            raise doxymwglobal.DoxyMWException("Not enough content in doxygen document to create MediaWiki page in " + self.filename)
        
        #Check for invalid characters in title, may need to use a DisplayTitle to display class properly
        self.title = data["title"]
        self.normtitle = DoxyMWTitle(data["title"], avoid=False)
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
        return TransclusionPage(self.normtitle, self)
    
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
                    doxymwglobal.msg(doxymwglobal.msgType.warning, "Unhandled link with unknown contents")
                    newStr = ""
            
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
    
    @property
    def newPages(self):
        pages = [self, DoxygenHTMLPage.globalCategory]
        #If we're not setting up transclusions, we add all the documentation to the nav categories,
        #otherwise the transclusions get added instead
        if not config["mediaWiki_setupTransclusions"]:
            pages.append(CategoryPage(DoxygenHTMLPage.globalNavCategory.mwtitle + " " + self.type, canEdit=False)
            if not config["mediaWiki_navCategoryExcludeMembers"] or self.target.type != "MEMBERS":
                pages.append(CategoryPage(DoxygenHTMLPage.globalNavCategory.mwtitle, canEdit=False)
        return pages
    
    #Gets the page title
    @property
    def mwtitle(self):
        return DoxygenHTMLPage.globalPrefix + " " + self.normtitle.title
    
    #Gets the page contents
    @property
    def mwcontents(self):
        #Sorting doesn't work too well with the original names
        #We reverse the order of the parts of the name from class to highest namespace
        sortKey = ".".join(reversed(self.normtitle.title.split(".")))
        
        #The noinclude DO NOT EDIT + link to transclusions (if they're enabled)
        return ("<noinclude>" +
        "\n'''''Do not edit this autogenerated page.'''''" +
        "\n''Edits will be lost upon running DoxyMWBot again. " +
        ("Edit [{{fullurl:" + self.normtitle.title + "|redirect=no}} " + self.normtitle.title + "] instead." if
        doxymwglobal.config["mediaWiki_setupTransclusions"]
        else "You must turn on transclusion to generate pages for you to add your content.") + "''" +
        "</noinclude>" +
        
        #DisplayTitle (If there is one)
        self.normtitle.displayTitle +
        
        #The doxygen infobox and actual page contents
        "\n" + self.infobox +
        "\n" + self.contents + 
        "\n" + self.footer + "| <small>DoxyMWBot is in no way affiliated with Doxygen.</small>" +
        
        #The categories
        "\n<noinclude>" +
        "\n[[" + DoxygenHTMLPage.globalCategory.mwtitle + "]]" + 
        ("\n[[" + DoxygenHTMLPage.globalNavCategory.mwtitle + "|" + sortKey + "]]" +
        ("\n[[" + DoxygenHTMLPage.globalNavCategory.mwtitle + " " + self.type + "|" + sortKey + "]]" if
        (not config["mediaWiki_navCategoryExcludeMembers"] or self.type != "MEMBERS") else
        else "")) if
        not config["mediaWiki_setupTransclusions"]
        else "") + 
        
        "\n</noinclude>"
        )
    
    def checkPageEdit(self, page):
        #Must have our docs category to modify!
        return DoxygenHTMLPage.globalCategory.isInCategory(page)
        

class TransclusionPage(DoxyMWUpdatePage):
    #Config values to change how the pages are made
    globalPrefix = None
    if "mediaWiki_transclusionPrefix" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionPrefix"] != "":
        globalPrefix = doxymwglobal.config["mediaWiki_transclusionPrefix"]
        
    globalCategory = None
    if "mediaWiki_transclusionCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionCategory"] != "":
        globalCategory = CategoryPage(doxymwglobal.config["mediaWiki_transclusionCategory"],hidden=True)
    else:
        raise doxymwglobal.ConfigException("A transclusion category must be defined or we can't properly clean them up later")
        

    def __init__(self, normtitle, target, **kwargs):
        super().__init__(**kwargs)
        self.normtitle = normtitle #Basic title of the transclusion page, same as doxygen docs page title
        self.target = target #Target DoxyMWPage of this transclusion page
    
    @property
    def newPages(self):
        pages = [self, TransclusionPage.globalCategory]
        if config["mediaWiki_setupTransclusions"]:
            pages.append(CategoryPage(DoxygenHTMLPage.globalNavCategory.mwtitle + " " + self.target.type, canEdit=False))
            if not config["mediaWiki_navCategoryExcludeMembers"] or self.target.type != "MEMBERS":
                pages.append(CategoryPage(DoxygenHTMLPage.globalNavCategory.mwtitle, canEdit=False))
        return pages
    
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
        #Sorting doesn't work too well with the original names
        #We reverse the order of the parts of the name from class to highest namespace
        sortKey = ".".join(reversed(self.normtitle.title.split(".")))
    
        return ("#REDIRECT [[" + self.target.mwtitle + "]]\n" + infoText + "\n\n" +
            self.normtitle.displayTitle +
            "[[" + TransclusionPage.globalCategory.mwtitle + "]]" + 
            ("\n[[" + DoxygenHTMLPage.globalNavCategory.mwtitle + "|" + sortKey + "]]" +
            ("\n[[" + DoxygenHTMLPage.globalNavCategory.mwtitle + " " + self.target.type + "|" + sortKey + "]]" if
            (not config["mediaWiki_navCategoryExcludeMembers"] or self.type != "MEMBERS") else
            else "")) if
            not config["mediaWiki_setupTransclusions"]
            else "")
        )
        
    def checkPageEdit(self, page):
        #Must have our category to modify!
        return TransclusionPage.globalCategory.isInCategory(page)
    
    def updatePage(self, site):
        page = self.getPage(site)
        if not self.checkPage(page):
            doxymwglobal.msg(doxymwglobal.msgType.warning, "Page failed safety check, will not be editted")
            return False          
        #If the page doesn't exist or is old redirect, make it as a blank redirect
        if not page.exists() or page.isRedirectPage():
            try:
                page.text = self.mwcontents
                page.save()
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                raise doxymwglobal.DoxyMWException("Couldn't create page")
            
            return True
            
        #Otherwise do nothing      
        return False

class ImagePage(DoxyMWPage):
    globalCategory = CategoryPage(DoxygenHTMLPage.globalCategory.normtitle.title + " IMAGE", parent=DoxygenHTMLPage.globalCategory)

    def __init__(self, fp, fn, **kwargs):
        super().__init__(**kwargs)
        
        #Check validity of file
        if not os.path.isfile(fp + "/" + fn):
            raise doxymwglobal.DoxyMWException("File " + fp + "/" + fn + " does not exist")
    
        self.filepath = fp
        self.filename = fn
        self.normtitle = DoxyMWTitle(fn)
    
    @property
    def newPages(self):
        return [self, ImagePage.globalCategory]
    
    @property
    def mwtitle(self):
        return "File:" + self.normtitle.title
    
    @property
    def mwcontents(self):
        return "Autogenerated Doxygen Image\n" + "[[" + ImagePage.globalCategory.mwtitle + "]]"
    
    def updatePage(self, site):
        imgPage = pywikibot.FilePage(site, self.normtitle.title)
        
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
        
class BotUserPage(DoxyMWUpdatePage):
    def __init__(self, site):
        self.normtitle = DoxyMWTitle(site.user())

    @property
    def newPages(self):
        return [self, DoxygenHTMLPage.globalCategory]
        
    @property
    def mwtitle(self):
        return "User:" + self.normtitle.title
    
    @property
    def mwcontents(self):
        return (
            "Hello, I am DoxyMWBot >:]" +
            "\n" + "This project is in no way affiliated with Doxygen" +
            "\n" + "More stuff will go here eventually, a FAQ, better description, etc" +
            "\n\n\n" + doxymwglobal.getUsage() +
            "\n[[" + DoxygenHTMLPage.globalCategory.mwtitle + "]]"
        )
    
    def checkPageEdit(self, page):
        return True
        
        
"""class StylesPage(DoxyMWReplaceSection):
    def __init__(self):
        
        
    @property
    def mwtitle(self):
        return "MediaWiki:Common.css"
    
    @property
    def mwcontents(self):
        putText = ""
        
        #Read the modified Doxygen styles
        
        #Read the custom DoxyMW styles"""