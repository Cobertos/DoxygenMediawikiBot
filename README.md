# DoxygenWikibot

A python bot running off of PyWikibot (distributed by MediaWiki) and Doxygen to convert Doxygen
documentation into MediaWiki markup and then upload it to a given MediaWiki site.
Licensed under the MIT License (should be included with the source code in LICENSE.txt)


SETUP:
You must create the family for your PyWikibot as described in their documentation. You must also run the 
setup.bat to setup the submodules properly (so they can be used as Python packages)

There's a ton of options in main.py that you'll also need to configure (like your installation of doxygen,
the configuration file you want to use, and MediaWiki preferences)

USAGE:
python main.py