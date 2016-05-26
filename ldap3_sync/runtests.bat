set IN_ENV=0

IF NOT EXIST "%~dp0tests\env" (
	virtualenv %~dp0\tests\env
	call %~dp0\tests\env\scripts\activate
	set IN_ENV=1
	pip install -r %~dp0\..\requirements.txt
	pip install -r %~dp0\tests\requirements.txt
    pip install django
)

IF IN_ENV EQU 0 (
	REM Only do this when not already in the virtualenv
	call %~dp0\tests\env\scripts\activate
)

python %~dp0\runtests.py