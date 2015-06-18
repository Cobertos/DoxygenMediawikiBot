import re

import pywikibot
from pywikibot import pagegenerators
from pywikibot.pagegenerators import GeneratorFactory

import doxymwglobal
from doxymwpage import DoxygenHTMLPage, CategoryPage, BotUserPage, TransclusionPage, ImagePage

class DoxyMWSite(object):
    def __init__(self, site):
        self.site = site
        site.login()
    
    #Returns a generator that matches all DoxyMWPages (That aren't non-redirect transclusions)
    def generator(self, preload=False):
        docsCategory = DoxygenHTMLPage.globalCategory
        transCategory = TransclusionPage.globalCategory
        #All the doc category documents
        fac = GeneratorFactory(site=self.site)
        #All the doc category documents
        fac.handleArg("-catr:" + docsCategory.normtitle.title)
        fac.handleArg("-subcatsr:" + docsCategory.normtitle.title)
        fac.handleArg("-page:" + docsCategory.mwtitle)
        #The transclusion category page
        fac.handleArg("-page:" + transCategory.mwtitle)
        gen1 = fac.getCombinedGenerator()
                
        #Find all the transclusion pages and only select the ones that are just redirects
        #Don't delete any other transclusion pages
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-catr:" + transCategory.normtitle.title)
        gen2 = fac.getCombinedGenerator()
        debugFiltered = doxymwglobal.option["printLevel"].value <= doxymwglobal.msgType.debug.value
        gen2 = pagegenerators.RedirectFilterPageGenerator(gen2, no_redirects=False, show_filtered=debugFiltered)
        
        #Combined generator
        gen = pagegenerators.CombinedPageGenerator([gen1, gen2])
        if preload: #Only use if this is the last generator in your generator list
            gen = pagegenerators.PreloadingGenerator(gen)
        return gen
    
    #CLEANUP - Cleans up MOST of DoxyMWBot's content from the wiki
    #Note: This deletes all uploaded doxygen docs and any transclusions that are just redirects
    #It will leave all other content alone
    def cleanup(self):
        gen = self.generator(preload=True)
        for page in gen:
            try:
                if not page.exists():
                    continue
                page.delete(reason="", prompt=doxymwglobal.option["interactive"])
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not delete page.")
                continue

        
    #UPDATE - Create/update all the wiki pages, deletes all old/unused pages
    def update(self, wikiPages):
        #Repeatedly used snippet
        def modifyAPage(data):
            try:
                data.updatePage(self.site)
                return True
            except doxymwglobal.DoxyMWException as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, str(e))
                return False
                
        #A set where we can retrieve all new items since last getNew call
        class setNewest(set):
            def __init__(self, *args):
                super().__init__(*args)
                self.oldSet = set()
            
            def union(self, otherSet):
                ret = setNewest(super().union(otherSet))
                ret.oldSet = self.oldSet.copy()
                return ret
            
            def getNew(self):
                newStuff = self.difference(self.oldSet)
                self.oldSet = self.copy()
                return newStuff
        
        #One shot pages we need to make
        #botUserPage = BotUserPage()
        
        #Top level category objects
        docsCategory = DoxygenHTMLPage.globalCategory
        transCategory = TransclusionPage.globalCategory
        
        #Categories we need to make
        neededCategories = setNewest()
        neededCategories.add(docsCategory)
        if doxymwglobal.config["mediaWiki_setupTransclusions"]:
            neededCategories.add(transCategory)
            
        #Images we need to upload (for shared images between pages)
        neededImages = setNewest()
         
        #Updated Pages
        updatedPages = []
        
        #Create/update all the documentation pages
        for pageData in wikiPages:
            #Create/overwrite the actual documentation page
            if modifyAPage(pageData):
                updatedPages.append(pageData.mwtitle)
                #This page made something, so make sure it's category is made
                cat = CategoryPage(doxymwglobal.config["mediaWiki_docsCategory"] + " " + pageData.type, parent=docsCategory)
                neededCategories.add(cat)
                    
            #Create the transclusion pages
            if doxymwglobal.config["mediaWiki_setupTransclusions"]:
                transPageData = pageData.getTransclusionPage()
                if modifyAPage(transPageData):
                    updatedPages.append(transPageData.mwtitle)
                     
            #Upload all images
            neededImages = neededImages.union(pageData.imgs)
            new = neededImages.getNew()
            for imgPageData in new:
                imgPageData.updatePage(self.site) #Image are uploaded directly to the wiki, not page needed
                updatedPages.append(imgPageData.mwtitle)
                neededCategories.add(ImagePage.globalCategory)
                
            #Create all added categories
            new = neededCategories.getNew()
            for catPageData in new:
                if modifyAPage(catPageData):
                    updatedPages.append(catPageData.mwtitle)
        
        #Delete all old pages
        gen = self.generator()
        #Filter out all updated pages
        #Filter requires all strings be regex patterns in a list in a special object based on family name and language
        updatedPages = [re.escape(str) for str in updatedPages]
        updatedPages = { "freespace" : { "en" : updatedPages }}
        gen = pagegenerators.PageTitleFilterPageGenerator(gen, updatedPages)
        gen = pagegenerators.PreloadingGenerator(gen)
        
        #Debug which pages we're going to delete
        if "whichDelete" in doxymwglobal.option["debug"]:
            fp = open("debug.txt", "w")
            fp.write("Updated\n")
            for item in updatedPages["freespace"]["en"]:
                fp.write(item + "\n")
            fp.write("\n\nDoxyMWPageGenerator Generated")
            for item in self.generator():
                fp.write(item.title() + "\n")
            fp.write("\n\nFilter Generated")
            for item in gen:
                fp.write(item.title() + "\n")
            return
        
        for page in gen:
            try:
                page.delete(reason="", prompt=doxymwglobal.option["interactive"])
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not delete old page.")
                continue
                
        #Uncache all the pages
        gen = self.generator(preload=True)
        for page in gen:
            try:
                if not page.exists():
                    continue
                page.purge()
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " purged")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Could not purge page.")
                continue