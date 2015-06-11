#Represents one page in both doxygen and media wiki
import re

from bs4 import BeautifulSoup

import doxymwglobal

class DoxygenMediaWikiException(Exception):
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
        
class DoxygenMediaWikiPage(object):
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
            raise DoxygenMediaWikiException("Not enough content in doxygen document to create MediaWiki page in " + self.filename)
        
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
    
    #Gets the page title
    @property
    def mwtitle(self):
        return doxymwglobal.config["mediaWiki_docsCategory"] + "_" + self.title
    
    #Gets the page contents
    @property
    def mwcontents(self):
        #The full contents is made up from multiple parts:
        #The noinclude DO NOT EDIT + link to transclusions (if they're enabled)
        #DisplayTitle (If there is one)
        #The actual contents of the page
        #The category
        
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
        "\n[[Category:" + doxymwglobal.config["mediaWiki_docsCategory"] + "_" + self.type + "]]" +
        "\n</noinclude>"
        )
    
    #Gets the transclusion page title
    @property
    def mwtranstitle(self):
        if "mediaWiki_transPrefix" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transPrefix"] != "":
            return doxymwglobal.config["mediaWiki_transPrefix"] + "_" + self.title
        else:
            return self.title
    
    #Gets the transclusion page contents
    @property
    def mwtranscontents(self):
        infoText = (
            "\n<!--"
            "\nTo add content alongside your coding documentation, you must edit this page."
            "\nRemove the redirect and add the text {{:" + self.mwtitle + "}} to transclude the coding documentation on this page"
            "\nIf you choose, you can rerun DoxyMWBot to add append transclusion to every non-redirect page you have created"
            "\n-->"
        )
    
        if "mediaWiki_transclusionCategory" in doxymwglobal.config and doxymwglobal.config["mediaWiki_transclusionCategory"] != "":
            return "#REDIRECT [[" + self.mwtitle + "]]\n" + infoText + "\n\n" + "[[Category:" + doxymwglobal.config["mediaWiki_transclusionCategory"] + "]]"
        else:
            return "#REDIRECT [[" + self.mwtitle + "]]\n" + infoText
            
class DoxygenMediaWikiCategory(object):

    def __init__(self,title,parentCat,hidden=True):
        self.title = title
        self.parent = parentCat
        self.hidden = hidden
    
    def __hash__(self):
        return hash(self.title)
    
    def __eq__(self, other):
        if isinstance(other, DoxygenMediaWikiCategory):
            return self.title == other.title
        return False
    
    def __ne__(self, other):
        return not self.__eq__(other)
    
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
    