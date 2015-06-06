::Set up the python bot on Windows
::Usage: setup.bat [-v]
:: -v = Set up virtual environment for project
@echo off

IF "%1"=="-d"
	GOTO dev_setup
ELSE
	GOTO normal_setup


::Setup a virtual environment for development
:dev_setup
echo Installing virtualenv...
pip install virtualenv

echo Creating virtual environment /venv ...
virtualenv venv
venv/Scripts/activate.bat
GOTO normal_setup


::Setup the bot for normal operation
:normal_setup
echo Running PyWikibot setup...
cd PyWikibot
python setup.py install

echo Creating __init__ for PyWikibot...
echo. > PyWikibot\__init__.py

echo Make sure to setup the user config as well as enabled all the API stuff on the wiki
pause