import re

import pywikibot
from pywikibot import pagegenerators
from pywikibot.pagegenerators import GeneratorFactory

import doxymwglobal
from doxymwpage import DoxygenHTMLPage, CategoryPage, BotUserPage, TransclusionPage, ImagePage, StylesPage

class DoxyMWSite(object):
    def __init__(self, site):
        self.site = site
        site.login()
         
    
    #Returns a generator that matches all DoxyMWPages (Pages that we FULLY own)
    #pywikibot=True gives a traditional pywikibot generator
    #pywikibot=False gives a list of tuples with a generator and a strategy based on the page so we can work on all pages
    def generator(self, pywikibot=True):
        docsCategory = DoxygenHTMLPage.globalCategory
        docsImgCategory = ImagePage.globalCategory
        transCategory = TransclusionPage.globalCategory
        navCategory = DoxygenHTMLPage.globalNavCategory
        botUserPage = BotUserPage(self.site)
        stylesPage = StylesPage()
        
        #Generator for categories
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-page:" + docsCategory.mwtitle)
        fac.handleArg("-subcatsr:" + docsCategory.normtitle.title)
        fac.handleArg("-page:" + transCategory.mwtitle)
        fac.handleArg("-page:" + navCategory.mwtitle)
        fac.handleArg("-subcatsr:" + navCategory.normtitle.title)
        fac.handleArg("-page:" + docsImgCategory.mwtitle)
        genCat = fac.getCombinedGenerator()
        
        #Generator for DoxyHTMLPages
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-cat:" + docsCategory.normtitle.title)
        genDoxy = fac.getCombinedGenerator()
        
        #Generator for Images
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-cat:" + docsImgCategory.normtitle.title)
        genImg = fac.getCombinedGenerator()
        
        #Generator for TransclusionPages
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-cat:" + transCategory.normtitle.title)
        genTrans = fac.getCombinedGenerator()
        if pywikibot:
            #Select only redirect transclusion pages
            debugFiltered = doxymwglobal.option["printLevel"].value <= doxymwglobal.msgType.debug.value
            genTrans = pagegenerators.RedirectFilterPageGenerator(genTrans, no_redirects=False, show_filtered=debugFiltered)
        
        #Generators for other pages
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-page:" + botUserPage.mwtitle)
        genUser = fac.getCombinedGenerator()
        fac = GeneratorFactory(site=self.site)
        fac.handleArg("-page:" + stylesPage.mwtitle)
        genStyles = fac.getCombinedGenerator()
        
        
        #Combined generator
        if pywikibot:
            return pagegenerators.CombinedPageGenerator([genCat, genDoxy, genImg, genTrans, genUser]) #No genStyles because we don't fully own it
        else:
            ret = []
            ret.append((genCat,CategoryPage.getStrategy()))
            ret.append((genDoxy,DoxygenHTMLPage.getStrategy()))
            ret.append((genImg,ImagePage.getStrategy()))
            ret.append((genTrans,TransclusionPage.getStrategy()))
            ret.append((genUser,BotUserPage.getStrategy()))
            ret.append((genStyles,StylesPage.getStrategy()))
            return ret
    
    #CLEANUP - Cleans up MOST of DoxyMWBot's content from the wiki
    #Note: This deletes all uploaded doxygen docs and any transclusions that are just redirects
    #It will leave all other content alone
    def cleanup(self):
        tuples = self.generator(pywikibot=False)
        for tup in tuples:
            gen = tup[0]
            strat = tup[1]
            for page in gen:
                if not page.exists():
                    continue
                try:
                    if strat.deletePage(page):
                        doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
                except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                    doxymwglobal.msg(doxymwglobal.msgType.warning, "Page " + page.title() + " could not be deleted: " + str(e))
                    continue
            
    #UPDATE - Create/update all the wiki pages, deletes all old/unused pages
    def update(self, wikiPages):
        #Keep a list of pages we're going to add in the info box
        infoBoxPages = set()
        for pageData in wikiPages:
            if pageData.type == "OTHER":
                infoBoxPages.add(pageData)
            
        #Retrieve all the pages we're making into a set
        allPages = set()
        allCategories = set()
        
        #One shot pages we need to make
        allPages.add(StylesPage())
        if doxymwglobal.config["mediaWiki_makeUserPage"]:
            botUserPage = BotUserPage(self.site)
            allPages.add(botUserPage)
            infoBoxPages.add(botUserPage)
        
        #Take the DoxygenHTMLPages and build the site
        for pageData in wikiPages:
            newPages = []
            
            #Transclusion Pages
            navCategoryAdd = pageData
            if doxymwglobal.config["mediaWiki_setupTransclusions"]:
                transPageData = pageData.getTransclusionPage()
                navCategoryAdd = transPageData
                
            #NavCategory Stuff
            navCategoryAdd.addCategory(CategoryPage(DoxygenHTMLPage.globalNavCategory.normtitle.title + " " + pageData.type, parent=DoxygenHTMLPage.globalNavCategory))
            if not (doxymwglobal.config["mediaWiki_navCategoryExcludeMembers"] and pageData.type == "MEMBERS"):
                navCategoryAdd.addCategory(DoxygenHTMLPage.globalNavCategory)
        
            #Add all the info box pages
            for infoBoxPageData in infoBoxPages:
                pageData.addInfoBoxPage(infoBoxPageData)
            
            #Data prepped, get all the pages
            if doxymwglobal.config["mediaWiki_setupTransclusions"]:
                newPages.extend(transPageData.newPages)
            newPages.extend(pageData.newPages) #All pages produced by the DoxygenHTMLPage
            
            #Filter out all categories and add them to a separate set
            for page in newPages[:]:
                if isinstance(page, CategoryPage):
                    newPages.remove(page)
                    allCategories.add(page)
                
            allPages = allPages.union(newPages)
        
        #Update all the pages
        updatedPages = []
        allPages = list(allPages)
        allPages[0:0] = list(allCategories) #Make sure categories go first!
        for pageData in allPages:
            try:
                pageData.updatePage(self.site)
                #Only put in updatedPages if it was successful
                updatedPages.append(pageData.mwtitle)
            except doxymwglobal.DoxyMWException as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, str(e))
        
        #Delete all old pages
        if "whichDelete" in doxymwglobal.option["debug"]:
            debugPath = doxymwglobal.debugPath()
            debugFp = open(debugPath + "/debug.txt", "w")
            debugFp.write("Updated\n")
            for item in updatedPages:
                debugFp.write(item + "\n")
            debugFp.write("\n\nFinal")
        
        tuples = self.generator(pywikibot=False)
        for tup in tuples:
            gen = tup[0]
            strat = tup[1]
            for page in gen:
                if not page.exists():
                    continue
                #Filter out update pages
                if page.title() in updatedPages:
                    continue
                
                #Debug which pages we're going to delete
                if "whichDelete" in doxymwglobal.option["debug"]:
                    debugFp.write(page.title() + "\n")
                    continue
                
                #Delete the old page
                try:
                    if strat.deletePage(page):
                        doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " deleted")
                except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                    doxymwglobal.msg(doxymwglobal.msgType.warning, "Page " + page.title() + " could not be deleted: " + str(e))
                    continue
        
        
                
        #Uncache mostly all the pages
        gen = self.generator(pywikibot=True)
        for page in gen:
            try:
                if not page.exists():
                    continue
                page.purge()
                doxymwglobal.msg(doxymwglobal.msgType.info, "Page " + page.title() + " purged")
            except (pywikibot.LockedPage, pywikibot.EditConflict, pywikibot.SpamfilterError) as e:
                doxymwglobal.msg(doxymwglobal.msgType.warning, "Page " + page.title() + " could not be purged: " + str(e))
                continue
            