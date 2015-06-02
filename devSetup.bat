::Setup for a python development environment
::Feel free to just setup PyWikibot in your root directory, this is just for development
@echo off
echo Installing virtualenv...
pip install virtualenv

echo Creating virtual environment /venv ...
virtualenv venv
venv/Scripts/activate.bat

echo Running PyWikibot setup...
cd PyWikibot
python setup.py install

echo Running Setup...
setup.bat

echo Make sure to setup the user config as well as enabled all the API stuff on the wiki
pause