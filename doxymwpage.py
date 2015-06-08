#Represents one page in both doxygen and media wiki
import re

from bs4 import BeautifulSoup

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
    
    #Find the title
    select = soup.select("div.header div.title")
    if len(select) <= 0:
        print("No title found")
        return None
    elif len(select) > 1:
        print("WARNING: Ambiguous title")
    data["title"] = select[0].decode_contents(formatter=None) #Straight unicode
    data["displayTitle"] = select[0].decode_contents(formatter="html") #With HTML &gt;-type entities
    
    #Find the contents
    select = soup.select("div.contents")
    if len(select) <= 0:
        print("No contents found")
        return None
    elif len(select) > 1:
        print("WARNING: Ambiguous contents")
    data["contents"] = select[0].decode_contents(formatter="html")
    
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
            if not internalLink:
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
        #TODO: Pic how we're going to style this on the wiki, just uses default
        newStr = "[[File:" + img.attrs["src"] + "]]"
        img.replace_with(newStr)
        
    #Convert <maps>
    #For now just delete them, we'll have to rely on a MW extension for this one later
    for map in soup("map"):
        map.replace_with("") 
        
    return (soup.decode_contents(formatter="html"), imgs)
        
class DoxygenMediaWikiPage(object):
    def __init__(self):
        #About the file this page came from (every file is a page)
        self.filepath = None
        self.filename = None
        
        #About the page itself
        self.type = None
        self.title = None
        self.displayTitle = None
        self.contents = None
        self.imgs = []
    
    #Extracts all the data from the file at self.filepath
    def extract(self):
        fp = open(self.filepath)
    
        #Extract the specific parts of the page for the wiki
        data = DoxygenHTMLExtractor(fp.read())
        
        if not "title" in data or not "contents" in data:
            raise DoxygenMediaWikiException("Not enough content in doxygen document to create MediaWiki page")
        
        #Check for invalid characters in title, may need to use a DisplayTitle to display class properly
        fakeTitle = re.sub("[\<\>\[\]\|\{\}_#]", "_", data["title"])
        if fakeTitle == data["title"]:
            self.title = data["title"]
            self.displayTitle = None #Same as title, no special characters
        else:
            self.title = fakeTitle
            self.displayTitle = data["displayTitle"]
        
        self.contents = data["contents"]
    
    #Converts all the data in this page to proper MediaWiki markup
    def convert(self, category, wikiPages):
        #Translate gathered data into MediaWiki markup (including links using wikiPages)
        #Only worry about the contents having markup
        self.contents, self.imgs = DoxygenHTMLConverter(self.contents, wikiPages)
        
        #Add categories to the pages
        header = "<noinclude>DO NOT EDIT: THIS IS AUTOGENERATED CONTENT<br>If you want to add data, setup transcriptions within DoxyMWBot<hr><br></noinclude>\n"
        if self.displayTitle:
            header += "{{DISPLAYTITLE:" + self.displayTitle + "}}"
        self.contents = header + self.contents
        self.contents += "\n<noinclude>[[Category:" + category + "_" + self.type + "]]</noinclude>"